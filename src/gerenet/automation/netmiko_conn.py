import base64
import hashlib
import re

from netmiko import ConnectHandler

from gerenet.automation.hostkeys import normalize_fingerprint

# Linha única começando com "display": aceita o comando sozinho ou com argumentos.
# (Com \n/\r já excluídos no laço, o fullmatch garante que nada além de uma linha
# display seja enviado — "display\nreboot" jamais chegaria ao equipamento.)
_ALLOWED_COMMAND = re.compile(r"display(?:\s|$).*")

# Denylist de aplicação: o plano vem do render próprio, mas um comando que
# escapa do stream de config (system-view/return/quit) ou persiste/destrói
# (save/reset/reboot/clear/delete) nunca deve ser enviado — defesa em
# profundidade (§12.3/§19). `shutdown` NÃO está aqui: o render emite
# `peer <ip> shutdown` (bgp_peer.j2:19) para sessões com shutdown=True.
_BLOCKED_CONFIG = re.compile(
    r"^(?:system-view|return|quit|save|reset|reboot|clear|delete)\b",
    re.IGNORECASE,
)


class HostKeyMismatch(Exception):
    def __init__(self, device: str, actual: str) -> None:
        self.device = device
        self.actual = actual
        super().__init__(
            f"Host key de {device} não confere (recebido {actual}). Não conectando — "
            "registre o fingerprint correto com `gerenet hostkey register`."
        )


class CommandNotAllowed(Exception):
    pass


class ConfigNotAllowed(Exception):
    """Comando fora da denylist de aplicação de configuração."""


class ConnectionFailed(Exception):
    pass


def _fingerprint_do_servidor(conn) -> str | None:
    """SHA-256 base64 do host key recebido, no formato OpenSSH 'sha256:...'."""
    try:
        chave = conn.remote_conn.transport.get_remote_server_key()
        b64 = base64.b64encode(hashlib.sha256(chave.asbytes()).digest()).decode()
        return f"sha256:{b64}"
    except Exception:  # noqa: BLE001 — fingerprint best-effort: sem chave ⇒ None
        return None


def _comando_config_proibido(cmd: str) -> bool:
    if "\n" in cmd or "\r" in cmd:
        return True
    return _BLOCKED_CONFIG.match(cmd.lstrip()) is not None


def _abre_conexao(device, username: str, password: str, settings):
    """ConnectHandler + validação de host key; levanta HostKeyMismatch/ConnectionFailed."""
    if not device.host_key_fingerprint:
        raise HostKeyMismatch(
            device.name,
            "nenhum fingerprint registrado — use `gerenet hostkey register` antes de coletar",
        )
    try:
        conn = ConnectHandler(
            device_type="huawei_vrp",
            host=device.management_address,
            port=device.ssh_port or 22,
            username=username,
            password=password,
            conn_timeout=settings.connect_timeout,
        )
    except Exception as exc:
        raise ConnectionFailed(f"Não foi possível conectar em {device.name}: {exc}") from exc
    try:
        actual = _fingerprint_do_servidor(conn)
        if actual is None:
            raise HostKeyMismatch(
                device.name,
                "indisponível — verifique a conectividade SSH e tente novamente",
            )
        # Normaliza os dois lados: o servidor calcula com padding base64 e o
        # `ssh-keygen -lf` do operador imprime sem — mesma chave, formas iguais.
        if normalize_fingerprint(actual) != normalize_fingerprint(device.host_key_fingerprint):
            raise HostKeyMismatch(device.name, normalize_fingerprint(actual))
        return conn
    except Exception:
        try:
            conn.disconnect()
        except Exception:  # noqa: BLE001, S110 — disconnect best-effort
            pass
        raise


def connect_and_run(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    """Conecta via Netmiko (huawei_vrp), valida host key e allowlist, executa comandos read-only."""
    for cmd in commands:
        if "\n" in cmd or "\r" in cmd or _ALLOWED_COMMAND.fullmatch(cmd) is None:
            raise CommandNotAllowed(f"Comando fora da allowlist read-only: {cmd!r}")
    conn = _abre_conexao(device, username, password, settings)
    try:
        saidas: dict[str, str] = {}
        for cmd in commands:
            saidas[cmd] = conn.send_command(cmd, read_timeout=settings.read_timeout)
        return saidas
    except Exception as exc:
        raise ConnectionFailed(f"Falha ao executar comandos em {device.name}: {exc}") from exc
    finally:
        try:
            conn.disconnect()
        except Exception:  # noqa: BLE001, S110 — disconnect best-effort no finally
            pass


def connect_and_apply(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    """Conecta, valida host key/denylist e aplica comandos via send_config_set (write path).

    Uma conexão por bloco (spec §6.4); a detecção de erros do VRP é feita pela
    saída (runner.ERROS_VRP) sobre o texto devolvido aqui.
    """
    for cmd in commands:
        if _comando_config_proibido(cmd):
            raise ConfigNotAllowed(f"Comando fora da denylist de aplicação: {cmd!r}")
    conn = _abre_conexao(device, username, password, settings)
    try:
        saida = conn.send_config_set(commands, read_timeout=settings.read_timeout)
        return {"config": saida}
    except Exception as exc:
        raise ConnectionFailed(f"Falha ao aplicar comandos em {device.name}: {exc}") from exc
    finally:
        try:
            conn.disconnect()
        except Exception:  # noqa: BLE001, S110 — disconnect best-effort no finally
            pass
