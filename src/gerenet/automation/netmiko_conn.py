import base64
import hashlib
import re

from netmiko import ConnectHandler

from gerenet.automation.hostkeys import normalize_fingerprint

# Linha única começando com "display": aceita o comando sozinho ou com argumentos.
# (Com \n/\r já excluídos no laço, o fullmatch garante que nada além de uma linha
# display seja enviado — "display\nreboot" jamais chegaria ao equipamento.)
_ALLOWED_COMMAND = re.compile(r"display(?:\s|$).*")


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


class ConnectionFailed(Exception):
    pass


def _fingerprint_do_servidor(conn) -> str | None:
    """SHA-256 base64 do host key recebido, no formato OpenSSH 'sha256:...'."""
    try:
        chave = conn.remote_conn.transport.get_remote_server_key()
        b64 = base64.b64encode(hashlib.sha256(chave.asbytes()).digest()).decode()
        return f"sha256:{b64}"
    except Exception:
        return None


def connect_and_run(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    """Conecta via Netmiko (huawei_vrp), valida host key e allowlist, executa comandos read-only."""
    if not device.host_key_fingerprint:
        raise HostKeyMismatch(
            device.name,
            "nenhum fingerprint registrado — use `gerenet hostkey register` antes de coletar",
        )
    for cmd in commands:
        if "\n" in cmd or "\r" in cmd or _ALLOWED_COMMAND.fullmatch(cmd) is None:
            raise CommandNotAllowed(f"Comando fora da allowlist read-only: {cmd!r}")

    try:
        conn = ConnectHandler(
            device_type="huawei_vrp",
            host=device.management_address,
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
        if actual != normalize_fingerprint(device.host_key_fingerprint):
            raise HostKeyMismatch(device.name, actual)
        saidas: dict[str, str] = {}
        for cmd in commands:
            saidas[cmd] = conn.send_command(cmd, read_timeout=settings.read_timeout)
        return saidas
    except HostKeyMismatch:
        raise
    except Exception as exc:
        raise ConnectionFailed(f"Falha ao executar comandos em {device.name}: {exc}") from exc
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
