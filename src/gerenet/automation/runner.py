"""Runner de coleta (read-only) e do fluxo de mudança controlada (spec §6/§12).

`run_collection` e `run_change` compartilham `_coleta_recursos` (COLLECTORS +
comandos por sessão) e `_grava_snapshot`. `run_change` executa os steps de uma
change request aprovada: por step — lock por device (§12.3, mesmo mecanismo da
coleta), coleta fresca salva como evidência pré-mudança, re-diff §5.3 do plano
congelado contra o encontrado, aplicação bloco a bloco com denylist
(`netmiko_conn.connect_and_apply`), coleta pós-mudança com verificação §13 e
classificação §4.1. Zero segredos em logs/snapshot/audit (§18): o que entra em
step/job/audit passa por `_mascarar_texto`.
"""
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import Session

from gerenet.automation import removal
from gerenet.automation.collectors import COLLECTORS, comandos_verbose
from gerenet.automation.netmiko_conn import connect_and_apply, connect_and_run
from gerenet.automation.parsers.huawei_vrp.merge import merge_parsed
from gerenet.automation.parsers.huawei_vrp.registry import parse_template
from gerenet.config import Settings, get_settings
from gerenet.db import SessionLocal
from gerenet.domain.models import AuditEvent, ChangeRequest, ChangeStep, DeviceSnapshot, JobRun
from gerenet.domain.services import devices as device_svc
from gerenet.domain.services.circuits import get_circuit
from gerenet.secrets.vault_store import VaultSecretStore


def _conectar_e_executar(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    return connect_and_run(device, username, password, commands, settings)


def _conectar_e_aplicar(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    return connect_and_apply(device, username, password, commands, settings)


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


# Erros de configuração do VRP (spec §6.4) — 1ª linha da saída do send_config_set
# costuma ser o comando ecoado; "^" é a marca de posição em linha própria.
ERROS_VRP = re.compile(r"% Error:|\^$|Incomplete command|Ambiguous command|Unrecognized command", re.MULTILINE)

# Palavras-chave cujo valor (1 token seguinte) nunca deve ir para log/audit (§18).
_VAZAMENTO = re.compile(r"(?i)\b(password|secret|token|senha|community)\b\s+\S+")


def _mascarar_texto(texto: str) -> str:
    """Mascara segredos em texto livre (erro de VRP/exceção) antes de gravar.

    O `audit.mascarar` do repo opera sobre painéis antes/depois de objetos;
    aqui o que registramos é texto: senhas/communities/tokens (precedidos da
    palavra-chave) viram "[mascarado]" (§18).
    """
    return _VAZAMENTO.sub("[mascarado]", texto)


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
            recursos, erros, arquivos_brutos = _coleta_recursos(session, dev, cred, settings, base)

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


def _coleta_recursos(session: Session, dev, cred: dict, settings, base: Path) -> tuple[dict, dict, dict]:
    """Roda os COLLECTORS do device (comandos por sessão quando aplicável).

    Devolve (recursos, erros, arquivos_brutos) — compartilhado entre a coleta
    (run_collection) e o backup/re-coleta do fluxo de mudança (run_change).
    """
    recursos: dict[str, object] = {}
    erros: dict[str, str] = {}
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
    return recursos, erros, arquivos_brutos


def _grava_snapshot(
    session: Session, dev, inicio: datetime, recursos: dict, erros: dict, arquivos: dict, actor: str,
) -> DeviceSnapshot:
    """DeviceSnapshot completo + touch_collection (compartilhado coleção/mudança)."""
    agora = datetime.now(UTC)
    snap = DeviceSnapshot(
        device_id=dev.id,
        status="success" if not erros else ("error" if not recursos else "partial"),
        resources=recursos, errors=erros, raw_files=arquivos,
        started_at=inicio, finished_at=agora,
        duration_ms=int((agora - inicio).total_seconds() * 1000),
    )
    session.add(snap)
    session.commit()
    versao = recursos.get("version")
    device_svc.touch_collection(
        session, dev,
        ok=bool(recursos),
        version=versao.get("version") if isinstance(versao, dict) else None,
        uptime=versao.get("uptime") if isinstance(versao, dict) else None,
    )
    session.commit()
    return snap


def _peer_remote(comandos: list[str]) -> str | None:
    """Endereço do par no bloco (`peer <ip> ...` ou `undo peer <ip>`), ou None."""
    for cmd in comandos:
        partes = cmd.split()
        if len(partes) >= 2 and partes[0] == "peer":
            return partes[1]
        if len(partes) >= 3 and partes[0] == "undo" and partes[1] == "peer":
            return partes[2]
    return None


def _peer_asn(comandos: list[str]) -> int | None:
    """ASN do par no bloco (`peer <ip> as-number <x>`), ou None se não constar."""
    for cmd in comandos:
        partes = cmd.split()
        for i, p in enumerate(partes):
            if p == "as-number" and i + 1 < len(partes):
                return int(partes[i + 1])
    return None


def _peer_familia(comandos: list[str]) -> str | None:
    """AFI do bloco (`ipv4-family unicast`/`ipv6-family unicast`), ou None."""
    if any(c.startswith("ipv6-family") for c in comandos):
        return "ipv6"
    if any(c.startswith("ipv4-family") for c in comandos):
        return "ipv4"
    return None


def _estado_do_bloco(bloco: dict, recursos: dict, texto: str) -> str:
    """Presença do objeto do bloco no encontrado fresco, por identidade (§5.1/§5.3).

    Mesma semântica do `_ja_existe` do plano: subinterface por nome; bgp_peer por
    (afi, peer, asn) — ASN não confirmado ⇒ ausente (conservador §5.1.3); ASN
    DIFERENTE para a mesma (afi, peer) ⇒ "conflito" (nunca "já presente");
    prefix_list e route-policy pelo padrão de texto no backup.
    """
    tipo = bloco.get("tipo")
    comandos = bloco.get("comandos") or []
    if not comandos:
        return "ausente"
    if tipo == "subinterface":
        partes = comandos[0].split(None, 1)
        if len(partes) < 2:
            return "ausente"
        nome = partes[1]
        if partes[0] == "undo":
            # "undo interface GigabitEthernet1/0/0.100" (bloco delete)
            nome = nome.split(" ", 1)[1] if " " in nome else nome
        return "consta" if nome in {i.get("nome") for i in recursos.get("interfaces", [])} else "ausente"
    if tipo == "bgp_peer":
        remote = _peer_remote(comandos)
        if remote is None:
            return "ausente"
        familia = _peer_familia(comandos)
        for linha in recursos.get("bgp_peers", []):
            if linha.get("peer") != remote:
                continue
            if familia is not None and linha.get("afi") != familia:
                continue
            asn = _peer_asn(comandos)
            if asn is None:
                # delete (`undo peer`): presença = (peer, afi) no encontrado
                return "consta"
            if linha.get("asn") is None:
                continue  # ASN não confirmado: conservador, não consta
            if asn == linha.get("asn"):
                return "consta"
            return "conflito"  # mesma (afi, peer), ASN diferente — não é "já presente"
        return "ausente"
    if tipo == "prefix_list":
        partes = comandos[0].split()
        if len(partes) >= 3 and partes[0] == "ip" and partes[1].endswith("-prefix"):
            return "consta" if f"{partes[0]} {partes[1]} {partes[2]} index" in texto else "ausente"
        if len(partes) > 3 and partes[0] == "undo" and partes[2].endswith("-prefix"):
            nome = partes[3]
            if f"ip ip-prefix {nome} index" in texto or f"ip ipv6-prefix {nome} index" in texto:
                return "consta"
            return "ausente"
        return "ausente"
    if tipo in ("route_policy_import", "route_policy_export"):
        partes = comandos[0].split()
        if len(partes) >= 2 and partes[0] == "route-policy":
            nome = partes[1]
        elif len(partes) >= 3 and partes[0] == "undo" and partes[1] == "route-policy":
            nome = partes[2]
        else:
            return "ausente"
        return "consta" if f"route-policy {nome} permit node" in texto else "ausente"
    return "ausente"  # tipo fora do repertório: reaplica (o comando é do nosso render)


def _re_diff(blocos: list[dict], recursos: dict, texto: str) -> tuple[list[dict], list[dict], str | None]:
    """§5.3 — bloco do plano congelado contra o encontrado fresco (PRÉ-mudança).

    Regras: conflito de identidade (ex.: mesmo (afi, peer) com ASN diferente)
    ⇒ aborta; tudo consta ⇒ pulado; tudo ausente ⇒ aplica; mistura de constas
    e ausentes entre creates ⇒ aborta — o plano congelado ficou desatualizado
    (config inalterada? §12.2). Devolve (a_aplicar, a_pular, erro_divergencia).
    """
    a_aplicar: list[dict] = []
    a_pular: list[dict] = []
    for bloco in blocos:
        estado = _estado_do_bloco(bloco, recursos, texto)
        if estado == "conflito":
            return [], [], (
                f"Estado divergente no objeto {bloco['tipo']} (#{bloco.get('objeto_id')}): "
                "identidade do encontrado não confere com o plano (§5.3)."
            )
        if bloco.get("acao", "create") == "delete":
            (a_pular if estado == "ausente" else a_aplicar).append(bloco)
        elif estado == "consta":
            a_pular.append(bloco)
        else:
            a_aplicar.append(bloco)
    if a_aplicar and any(bloco.get("acao", "create") == "create" for bloco in a_pular):
        # Só create consta+ausente no mesmo plano é divergência (plano congelado
        # desatualizado, §12.2). Remove (delete) parcial é natural: pular o que
        # já não existe e remover o que existe é a própria idempotência (§3.2) —
        # sem abort, o step reexecutável converge sem reconciliar o plano.
        bloco = next(b for b in a_pular if b.get("acao", "create") == "create")
        return [], [], (
            f"Estado divergente no objeto {bloco['tipo']} (#{bloco.get('objeto_id')}): apenas "
            "parte do plano consta do encontrado (config inalterada? §12.2) — "
            "reexecute com plano atualizado."
        )
    return a_aplicar, a_pular, None


def _aplica_blocos(session: Session, dev, cred: dict, blocos: list[dict], settings) -> str | None:
    """Bloco a bloco (uma conexão por bloco, §6.4); None = ok, senão primeira linha de erro VRP."""
    for bloco in blocos:
        comandos = bloco.get("comandos") or []
        if not comandos:
            continue
        saida = _conectar_e_aplicar(dev, cred["username"], cred["password"], comandos, settings)
        texto = saida.get("config", "")
        if ERROS_VRP.search(texto):
            linha = next((l.strip() for l in texto.splitlines() if ERROS_VRP.search(l)), "Erro do VRP")
            return linha[:500]
    return None


def _verifica_aplicados(step: ChangeStep, snap: DeviceSnapshot) -> list[dict]:
    """Pós-validação §13: cada bloco do plano consta (create)/não consta (delete)
    do encontrado pós-mudança — com a mesma identidade do re-diff."""
    recursos = snap.resources or {}
    texto = removal.texto_backup(snap)
    items: list[dict] = []
    for bloco in step.plano_json or []:
        estado = _estado_do_bloco(bloco, recursos, texto)
        objeto = f"{bloco['tipo']} (#{bloco.get('objeto_id')})"
        if bloco.get("acao", "create") == "delete":
            if estado in ("consta", "conflito"):
                items.append({
                    "tipo": f"{bloco['tipo']}.presente", "severidade": "critica",
                    "esperado": f"{objeto} removido", "encontrado": f"{objeto} ainda presente",
                    "acao": "Remover manualmente.",
                })
        elif estado in ("ausente", "conflito"):
            items.append({
                "tipo": f"{bloco['tipo']}.ausente", "severidade": "critica",
                "esperado": f"{objeto} presente", "encontrado": f"{objeto} ausente",
                "acao": "Aplicar manualmente e revalidar.",
            })
    return items


def _executa_step(
    session: Session, cr, step, dev, cred, settings, base, *, actor: str, origin: str,
) -> str:
    """Um step: coleta fresca → evidência pré-mudança → re-diff → aplicação → pós-validação.

    Retorna "aplicado" | "pulado" | "falhou" (e preenche step/JobRun/auditoria).
    """
    inicio = datetime.now(UTC)
    job = JobRun(device_id=dev.id, actor=actor, origin=origin, kind="change", status="running")
    session.add(job)
    session.commit()
    try:
        if cred is None:
            raise ValueError(f"{dev.name} não possui grupo de credencial.")
        recursos_pre, erros_pre, arquivos_pre = _coleta_recursos(session, dev, cred, settings, base / "pre")
        snap_pre = _grava_snapshot(session, dev, inicio, recursos_pre, erros_pre, arquivos_pre, actor)
        step.backup_snapshot_id = snap_pre.id  # backup pré-mudança §12.3
        if erros_pre and not recursos_pre:
            raise ValueError(_mascarar_texto(f"Coleta pré-mudança sem recursos: {list(erros_pre)[:3]}"))

        # re-diff §5.3 do plano congelado contra o encontrado fresco
        texto_pre = removal.texto_backup(snap_pre)
        a_aplicar, a_pular, divergencia = _re_diff(step.plano_json or [], recursos_pre, texto_pre)
        if divergencia is not None:
            raise ValueError(divergencia)

        erro = _aplica_blocos(session, dev, cred, a_aplicar, settings)
        if erro is not None:
            step.status = "falhou"
            step.erro = _mascarar_texto(erro)[:500]
            step.finished_at = datetime.now(UTC)
            job.status = "error"
            job.error = step.erro
            job.finished_at = step.finished_at
            session.commit()
            session.add(AuditEvent(
                type="change.step_failed", actor=actor,
                details={"change_request_id": cr.id, "change_step_id": step.id,
                         "device_id": dev.id, "error": step.erro},
            ))
            session.commit()
            return "falhou"

        # pós-coleta de verificação (a "validação do resultado" §12.3/§13)
        recursos_pos, erros_pos, arquivos_pos = _coleta_recursos(session, dev, cred, settings, base / "pos")
        snap_pos = _grava_snapshot(session, dev, datetime.now(UTC), recursos_pos, erros_pos, arquivos_pos, actor)
        if erros_pos and not recursos_pos:
            raise ValueError(_mascarar_texto(f"Coleta pós-mudança sem recursos: {list(erros_pos)[:3]}"))
        items = _verifica_aplicados(step, snap_pos)
        step.post_check_json = {"snapshot_id": snap_pos.id, "items": items}

        label = "aplicado" if a_aplicar else "pulado"
        step.status = label
        step.finished_at = datetime.now(UTC)
        job.status = "success"
        job.finished_at = step.finished_at
        session.commit()
        session.add(AuditEvent(
            type="change.step_applied" if label == "aplicado" else "change.step_skipped",
            actor=actor,
            details={"change_request_id": cr.id, "change_step_id": step.id,
                     "device_id": dev.id, "blocos": len(a_aplicar), "pulados": len(a_pular)},
        ))
        session.commit()
        return label
    except Exception as exc:  # noqa: BLE001 — contrato string
        session.rollback()
        step.status = "falhou"
        step.erro = _mascarar_texto(str(exc))[:500]
        step.finished_at = datetime.now(UTC)
        job.status = "error"
        job.error = step.erro
        job.finished_at = step.finished_at
        session.commit()
        session.add(AuditEvent(
            type="change.step_failed", actor=actor,
            details={"change_request_id": cr.id, "change_step_id": step.id,
                     "device_id": dev.id, "error": step.erro},
        ))
        session.commit()
        return "falhou"


def run_change(
    change_request_id: int,
    *,
    actor: str = "worker",
    origin: str = "rq",
    settings: Settings | None = None,
    session_override: Session | None = None,
) -> dict:
    """Executa uma change request aprovada (spec §6): por step — lock por device,
    coleta fresca (backup pré-mudança §12.3), re-diff §5.3, aplicação bloco a
    bloco com denylist, nova coleta + pós-validação, classificação §6.5."""
    settings = settings or get_settings()
    session_propria = session_override is None
    session = session_override or SessionLocal()
    redis: Redis | None = None
    cr: ChangeRequest | None = None
    try:
        token = secrets.token_hex(16)
        redis = Redis.from_url(settings.redis_url)
        cr = session.get(ChangeRequest, change_request_id)
        if cr is None:
            raise ValueError(f"Change request {change_request_id} não encontrada.")
        chave_cr = f"gerenet:lock:change:{change_request_id}"
        if not redis.set(chave_cr, token, nx=True, ex=settings.lock_ttl_seconds):
            session.add(
                AuditEvent(
                    type="change.skipped", actor=actor,
                    details={"change_request_id": change_request_id, "reason": "lock"},
                )
            )
            session.commit()
            return {"status": "error", "error": "Change request já está sendo executada (lock ativo)."}
        try:
            if cr.status == "aprovado":
                cr.status = "executando"
                session.add(
                    AuditEvent(
                        type="change.executing", actor=actor,
                        details={"change_request_id": cr.id, "criticidade": cr.criticidade},
                    )
                )
                session.commit()
            elif cr.status != "executando":
                session.add(
                    AuditEvent(
                        type="change.skipped", actor=actor,
                        details={"change_request_id": cr.id, "reason": f"estado {cr.status}"},
                    )
                )
                session.commit()
                return {"status": "error", "error": f"Change request não executável (estado {cr.status})."}

            get_circuit(session, cr.circuit_id)  # setup: NotFoundError propaga (falha de setup)
            base = settings.backups_dir / f"change-{cr.id}" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            resultados: list[str] = []
            for step in cr.steps:
                if step.status != "pendente":
                    continue
                dev = device_svc.get_device(session, step.device_id)
                cred = None
                grupo = dev.credential_group
                if grupo is not None:
                    cred = VaultSecretStore(settings.vault_url, settings.vault_token).get_credential(grupo.vault_path)

                chave_dev = f"gerenet:lock:device:{dev.id}"
                if not redis.set(chave_dev, token, nx=True, ex=settings.lock_ttl_seconds):
                    step.status = "falhou"
                    step.erro = "Equipamento ocupado (lock ativo) — reexecute após a coleta em andamento."
                    step.finished_at = datetime.now(UTC)
                    job = JobRun(
                        device_id=dev.id, actor=actor, origin=origin,
                        kind="change", status="error", error=step.erro,
                    )
                    session.add(job)
                    session.commit()
                    session.add(AuditEvent(
                        type="change.step_failed", actor=actor,
                        details={"change_request_id": cr.id, "change_step_id": step.id,
                                 "device_id": dev.id, "reason": "lock"},
                    ))
                    session.commit()
                    resultados.append("falhou")
                    continue
                try:
                    resultado_do_step = _executa_step(
                        session, cr, step, dev, cred, settings, base, actor=actor, origin=origin,
                    )
                    resultados.append(resultado_do_step)
                finally:
                    _liberta_lock(redis, chave_dev, token)

            if resultados:
                post_criticas = any(
                    step.post_check_json
                    and any(i["severidade"] == "critica" for i in step.post_check_json.get("items", []))
                    for step in cr.steps if step.status in ("aplicado", "pulado")
                )
                if all(r in ("aplicado", "pulado") for r in resultados):
                    status_cr = "com_divergencia" if post_criticas else "aplicado"
                elif any(r in ("aplicado", "pulado") for r in resultados):
                    status_cr = "parcial"
                else:
                    status_cr = "erro"
                cr.status = status_cr
                # "aplicado" vira "change.applied" (nome do evento em inglês, como
                # approved/rejected); os demais status usam o nome PT do enum.
                tipo_audit = "change.applied" if status_cr == "aplicado" else f"change.{status_cr}"
                session.add(
                    AuditEvent(type=tipo_audit, actor=actor, details={"change_request_id": cr.id})
                )
                session.commit()
                return {"status": status_cr}
            return {"status": "erro", "error": "Change request sem steps pendentes."}
        except Exception as exc:  # noqa: BLE001 — contrato dict preservado
            if cr.status == "executando":
                cr.status = "erro"
                session.add(
                    AuditEvent(
                        type="change.errors", actor=actor,
                        details={"change_request_id": cr.id, "error": _mascarar_texto(str(exc))[:500]},
                    )
                )
                session.commit()
            return {"status": "error", "error": str(exc)}
        finally:
            _liberta_lock(redis, chave_cr, token)
    except Exception as exc:  # noqa: BLE001 — falha pré-lock
        return {"status": "error", "error": str(exc)}
    finally:
        if redis is not None:
            redis.close()
        if session_propria:
            session.close()
