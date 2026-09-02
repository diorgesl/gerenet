import secrets
from datetime import datetime, timezone
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import Session

from gerenet.automation.collectors import COLLECTORS
from gerenet.automation.netmiko_conn import connect_and_run
from gerenet.automation.parsers.huawei_vrp.registry import parse_template
from gerenet.config import Settings, get_settings
from gerenet.db import SessionLocal
from gerenet.domain.models import AuditEvent, DeviceSnapshot, JobRun
from gerenet.domain.services import devices as device_svc
from gerenet.secrets.vault_store import VaultSecretStore


def _conectar_e_executar(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    return connect_and_run(device, username, password, commands, settings)


def _nome_do_arquivo(comando: str) -> str:
    partes = comando.split()
    return partes[1] if len(partes) > 1 else "output"


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
    except Exception:  # redis indisponível na liberação: TTL expira sozinho
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
    job: JobRun | None = None
    snapshot: DeviceSnapshot | None = None

    redis = Redis.from_url(settings.redis_url)
    chave_lock = f"gerenet:lock:device:{device_id}"
    # Token único por execução: a liberação só apaga o lock se ainda for nosso.
    token = secrets.token_hex(16)
    if not redis.set(chave_lock, token, nx=True, ex=settings.lock_ttl_seconds):
        redis.close()
        if session_propria:
            session.close()
        return {"status": "error", "snapshot_id": None, "error": "Equipamento já está sendo coletado (lock ativo)."}
    try:
        dev = device_svc.get_device(session, device_id)
        grupo = dev.credential_group
        if grupo is None:
            raise ValueError(f"{dev.name} não possui grupo de credencial.")

        job = JobRun(device_id=dev.id, actor=actor, origin=origin, kind="collect", status="running")
        session.add(job)
        session.commit()

        cred = VaultSecretStore(settings.vault_url, settings.vault_token).get_credential(grupo.vault_path)

        inicio = datetime.now(timezone.utc)
        snapshot = DeviceSnapshot(device_id=dev.id, status="error")
        session.add(snapshot)
        session.commit()

        base = settings.backups_dir / dev.name / inicio.strftime("%Y%m%dT%H%M%S")
        erros: dict[str, str] = {}
        recursos: dict[str, object] = {}
        arquivos_brutos: dict[str, list[str]] = {}
        for nome, spec in COLLECTORS.items():
            try:
                saidas = _conectar_e_executar(dev, cred["username"], cred["password"], spec["commands"], settings)
                lista_arquivos: list[str] = []
                for comando, saida in saidas.items():
                    caminho = base / nome / f"{_nome_do_arquivo(comando)}.txt"
                    caminho.parent.mkdir(parents=True, exist_ok=True)
                    caminho.write_text(saida, encoding="utf-8")
                    lista_arquivos.append(str(caminho))
                arquivos_brutos[nome] = lista_arquivos
                if spec["parser"]:
                    linhas = parse_template(spec["parser"], saidas[spec["commands"][0]])
                    recursos[nome] = linhas[0] if linhas else {"erro": "Saída sem registros parseáveis."}
                else:
                    recursos[nome] = {"backup": True}
            except Exception as exc:  # HostKeyMismatch, ConnectionFailed, falha de parse etc.
                erros[nome] = str(exc)

        snapshot.finished_at = datetime.now(timezone.utc)
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
    except Exception as exc:
        if job is not None:
            job.status = "error"
            job.finished_at = datetime.now(timezone.utc)
            session.commit()
        return {"status": "error", "snapshot_id": snapshot.id if snapshot else None, "error": str(exc)}
    finally:
        _liberta_lock(redis, chave_lock, token)
        if session_propria:
            session.close()
        redis.close()
