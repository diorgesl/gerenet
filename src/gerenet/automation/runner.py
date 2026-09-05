import re
import secrets
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy.orm import Session

from gerenet.automation.collectors import COLLECTORS, comandos_verbose
from gerenet.automation.netmiko_conn import connect_and_run
from gerenet.automation.parsers.huawei_vrp.merge import merge_parsed
from gerenet.automation.parsers.huawei_vrp.registry import parse_template
from gerenet.config import Settings, get_settings
from gerenet.db import SessionLocal
from gerenet.domain.models import AuditEvent, DeviceSnapshot, JobRun
from gerenet.domain.services import devices as device_svc
from gerenet.secrets.vault_store import VaultSecretStore


def _conectar_e_executar(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    return connect_and_run(device, username, password, commands, settings)


def _nome_do_arquivo(comando: str) -> str:
    """Stable file slug for the collected command (ex.: `bgp-ipv6-peer.txt`)."""
    nome = comando.removeprefix("display ").replace(" ", "-")
    return re.sub(r"[^0-9A-Za-z._-]+", "-", nome).strip("-") or "output"


_LIBERTA_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


def _liberta_lock(redis: Redis, chave_lock: str, token: str) -> None:
    """Libera o lock via compare-and-delete: só apaga se o valor ainda for o nosso token.

    Se o TTL expirou e outro worker readquiriu, o lock dele não é tocado. Falha de
    comunicação com o Redis aqui é ignorada — o TTL expira sozinho e o resultado
    da coleta não pode ser mascarado por falha na liberação.
    """
    try:
        redis.eval(_LIBERTA_LOCK, 1, chave_lock, token)
    except Exception:  # noqa: BLE001, S110 — redis indisponível na liberação: TTL expira sozinho
        pass


def run_collection(
    device_id: int,
    *,
    actor: str = "worker",
    origin: str = "rq",
    settings: Settings | None = None,
    session_override: Session | None = None,
) -> dict:
    settings = settings or get_settings()
    session_propria = session_override is None
    session = session_override or SessionLocal()
    redis: Redis | None = None
    job: JobRun | None = None
    snapshot: DeviceSnapshot | None = None

    chave_lock = f"gerenet:lock:device:{device_id}"
    try:
        # Token único por execução: a liberação só apaga o lock se ainda for nosso.
        token = secrets.token_hex(16)
        redis = Redis.from_url(settings.redis_url)
        if not redis.set(chave_lock, token, nx=True, ex=settings.lock_ttl_seconds):
            # Lock ativo não é falha desta execução (outro job é o dono), mas deixa
            # registro do porquê — senão o operador só vê o job "sumido" (§18).
            session.add(
                AuditEvent(type="collect.skipped", actor=actor, details={"device_id": device_id, "reason": "lock"})
            )
            session.commit()
            return {"status": "error", "snapshot_id": None, "error": "Equipamento já está sendo coletado (lock ativo)."}
        try:
            dev = device_svc.get_device(session, device_id)
            # JobRun nasce ANTES da validação de grupo: falha pré-snapshot também
            # deixa trilha no banco (motivo em job.error + evento collect.failed).
            job = JobRun(device_id=dev.id, actor=actor, origin=origin, kind="collect", status="running")
            session.add(job)
            session.commit()

            grupo = dev.credential_group
            if grupo is None:
                raise ValueError(f"{dev.name} não possui grupo de credencial.")

            cred = VaultSecretStore(settings.vault_url, settings.vault_token).get_credential(grupo.vault_path)

            inicio = datetime.now(UTC)
            snapshot = DeviceSnapshot(device_id=dev.id, status="error")
            session.add(snapshot)
            session.commit()

            base = settings.backups_dir / dev.name / inicio.strftime("%Y%m%dT%H%M%S")
            erros: dict[str, str] = {}
            recursos: dict[str, object] = {}
            arquivos_brutos: dict[str, list[str]] = {}
            for nome, spec in COLLECTORS.items():
                try:
                    if spec.get("alvo_sessoes"):
                        # SoT-driven commands: one verbose command per active BGP
                        # session of the device (spec §4.1); no sessions -> the
                        # resource is skipped, the collection does not fail (§12).
                        comandos = comandos_verbose(spec, dev.id, session)
                        if not comandos:
                            continue
                    else:
                        comandos = spec["commands"]
                    saidas = _conectar_e_executar(dev, cred["username"], cred["password"], comandos, settings)
                    lista_arquivos: list[str] = []
                    for comando, saida in saidas.items():
                        caminho = base / nome / f"{_nome_do_arquivo(comando)}.txt"
                        caminho.parent.mkdir(parents=True, exist_ok=True)
                        caminho.write_text(saida, encoding="utf-8")
                        lista_arquivos.append(str(caminho))
                    arquivos_brutos[nome] = lista_arquivos
                    if spec.get("parser"):
                        # Simple resource: one command, one parse, first record as dict.
                        linhas = parse_template(spec["parser"], saidas[spec["commands"][0]])
                        recursos[nome] = linhas[0] if linhas else {"erro": "Saída sem registros parseáveis."}
                    elif spec.get("parsers"):
                        # Multi-command resource: per-command parser + merge into the shape.
                        por_comando = {
                            comando: parse_template(spec["parsers"][comando], saidas[comando])
                            for comando in comandos
                        }
                        recursos[nome] = merge_parsed(spec["merge"], por_comando)
                    elif spec.get("alvo_sessoes"):
                        # SoT-targeted resource: the same parser for every session command.
                        por_comando = {
                            comando: parse_template(spec["parser_alvo"], saidas[comando])
                            for comando in comandos
                        }
                        recursos[nome] = merge_parsed(spec["merge"], por_comando)
                    else:
                        recursos[nome] = {"backup": True}
                except Exception as exc:  # noqa: BLE001 — falha de recurso vira erro no dict
                    erros[nome] = str(exc)

            snapshot.finished_at = datetime.now(UTC)
            snapshot.duration_ms = int((snapshot.finished_at - inicio).total_seconds() * 1000)
            snapshot.resources = recursos
            snapshot.errors = erros
            snapshot.raw_files = arquivos_brutos
            snapshot.status = "success" if not erros else ("error" if not recursos else "partial")

            versao = recursos.get("version")
            device_svc.touch_collection(
                session,
                dev,
                ok=bool(recursos),
                version=versao.get("version") if isinstance(versao, dict) else None,
                uptime=versao.get("uptime") if isinstance(versao, dict) else None,
            )

            job.status = snapshot.status
            job.finished_at = snapshot.finished_at
            job.duration_ms = snapshot.duration_ms
            job.snapshot_id = snapshot.id
            session.commit()

            if erros:
                session.add(
                    AuditEvent(type="collect.errors", actor=actor, details={"device_id": dev.id, "errors": erros})
                )
                session.commit()

            return {"status": snapshot.status, "snapshot_id": snapshot.id}
        except Exception as exc:  # noqa: BLE001 — contrato dict preservado em qualquer falha
            if job is not None:
                job.status = "error"
                job.error = str(exc)
                job.finished_at = datetime.now(UTC)
                session.commit()
                session.add(
                    AuditEvent(type="collect.failed", actor=actor, details={"device_id": device_id, "error": str(exc)})
                )
                session.commit()
            return {"status": "error", "snapshot_id": snapshot.id if snapshot else None, "error": str(exc)}
        finally:
            _liberta_lock(redis, chave_lock, token)
    except Exception as exc:  # noqa: BLE001 — falha pré-lock mantém contrato dict
        # Falha ANTES de adquirir o lock (Redis fora do ar etc.): o contrato dict
        # é mantido; sessão e client são fechados no finally externo.
        return {"status": "error", "snapshot_id": None, "error": str(exc)}
    finally:
        if redis is not None:
            redis.close()
        if session_propria:
            session.close()
