import base64
import hashlib
import socket

import paramiko


class HostKeyScanError(Exception):
    """Falha ao obter a host key por SSH (rede, timeout ou handshake)."""


def fingerprint_ssh(host: str, port: int, timeout: float) -> str:
    """Lê a host key do servidor SSH sem autenticar e devolve 'sha256:...'.

    A troca de chaves do SSH 2 acontece antes do login, então nenhuma credencial
    é necessária para obter o fingerprint. A fórmula é a mesma da verificação na
    coleta (netmiko_conn._fingerprint_do_servidor); o resultado sai sem padding,
    como o `ssh-keygen -lf` imprime.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            transport = paramiko.Transport(sock)
            try:
                transport.start_client(timeout=timeout)
                chave = transport.get_remote_server_key()
                b64 = base64.b64encode(hashlib.sha256(chave.asbytes()).digest()).decode()
                return normalize_fingerprint(f"sha256:{b64}")
            finally:
                transport.close()
    except (OSError, paramiko.SSHException, EOFError) as exc:
        raise HostKeyScanError(f"{host}:{port}: {exc}") from exc


def normalize_fingerprint(fingerprint: str) -> str:
    """Canonicaliza 'SHA256:AbC=' / '  sha256:abc  ' para 'sha256:AbC' (sem padding).

    O esquema vira minúsculo; o corpo base64 preserva maiúsculas/minúsculas —
    ele é dado do hash e não pode ser alterado. Só o padding '=' final é removido:
    'ssh-keygen -lf' imprime sem padding e o cálculo sha256 do lado servidor
    adiciona; a mesma chave precisa canonicalizar igual nos dois lados.
    """
    fp = fingerprint.strip().rstrip("=")
    if ":" in fp:
        esquema, valor = fp.split(":", 1)
        return f"{esquema.strip().lower()}:{valor.strip()}"
    return fp
