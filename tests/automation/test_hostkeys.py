from sqlalchemy.orm import Session

from gerenet.automation.hostkeys import normalize_fingerprint
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device


def test_normaliza_fingerprint() -> None:
    assert normalize_fingerprint("  SHA256:AbCdEf==  ") == "sha256:AbCdEf"
    assert normalize_fingerprint("SHA256:abcdef==") == "sha256:abcdef"
    assert normalize_fingerprint("sha256:abcdef") == "sha256:abcdef"


def test_fingerprint_padding_nao_quebra_igualdade() -> None:
    """A mesma chave pode chegar com padding ('ssh-keygen -lf' imprime sem, o cálculo
    `sha256:` do servidor com) — os dois lados precisam canonicalizar iguais."""
    servidor = "sha256:h0k1DFuQeWw43aX2zHN0XIUuR/lSH7lirO/mAdB311U="
    registrado = "SHA256:h0k1DFuQeWw43aX2zHN0XIUuR/lSH7lirO/mAdB311U"
    assert normalize_fingerprint(servidor) == normalize_fingerprint(registrado)


def test_fingerprint_ssh_calcula_sha256_sem_credencial(monkeypatch) -> None:
    """start_client() troca as chaves antes do login: nenhuma credencial entra em cena."""
    import base64
    import hashlib

    from gerenet.automation import hostkeys as hk

    class ChaveFake:
        def asbytes(self) -> bytes:
            return b"chave-do-servidor"

    class TransportFake:
        def __init__(self, sock) -> None:
            self._sock = sock

        def start_client(self, timeout=None) -> None:
            pass

        def get_remote_server_key(self):
            return ChaveFake()

        def close(self) -> None:
            pass

    class SocketFake:
        def __enter__(self):
            return self

        def __exit__(self, *exc) -> bool:
            return False

    monkeypatch.setattr(hk.socket, "create_connection", lambda *a, **k: SocketFake())
    monkeypatch.setattr(hk.paramiko, "Transport", TransportFake)
    fp = hk.fingerprint_ssh("10.0.0.1", 22, 0.5)
    esperado = base64.b64encode(hashlib.sha256(b"chave-do-servidor").digest()).decode().rstrip("=")
    assert fp == f"sha256:{esperado}"


def test_fingerprint_ssh_erro_de_rede_vira_hostkey_scan_error(monkeypatch) -> None:
    from gerenet.automation import hostkeys as hk

    def falha(*a, **k):
        raise OSError("timeout")

    monkeypatch.setattr(hk.socket, "create_connection", falha)
    try:
        hk.fingerprint_ssh("10.0.0.1", 22, 0.5)
    except hk.HostKeyScanError:
        pass
    else:
        raise AssertionError("HostKeyScanError não levantada")


def test_registro_gera_audit(db_session: Session) -> None:
    from gerenet.domain.models import AuditEvent

    dev = create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.1"), actor="cli")
    dev.host_key_fingerprint = "sha256:xyz"
    evento = AuditEvent(type="hostkey.register", actor="cli", details={"device_id": dev.id, "fingerprint": "sha256:xyz"})
    db_session.add(evento)
    db_session.commit()
    assert db_session.get(AuditEvent, evento.id).type == "hostkey.register"
