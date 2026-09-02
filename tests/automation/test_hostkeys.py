from sqlalchemy.orm import Session

from gerenet.automation.hostkeys import normalize_fingerprint
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device


def test_normaliza_fingerprint() -> None:
    assert normalize_fingerprint("  SHA256:AbCdEf==  ") == "sha256:AbCdEf=="
    assert normalize_fingerprint("SHA256:abcdef==") == "sha256:abcdef=="


def test_registro_gera_audit(db_session: Session) -> None:
    from gerenet.domain.models import AuditEvent

    dev = create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.1"), actor="cli")
    dev.host_key_fingerprint = "sha256:xyz"
    evento = AuditEvent(type="hostkey.register", actor="cli", details={"device_id": dev.id, "fingerprint": "sha256:xyz"})
    db_session.add(evento)
    db_session.commit()
    assert db_session.get(AuditEvent, evento.id).type == "hostkey.register"
