from sqlalchemy.orm import Session

from gerenet.domain.models import CredentialGroup, Device


def test_device_roundtrip(db_session: Session) -> None:
    grupo = CredentialGroup(
        name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao"
    )
    db_session.add(grupo)
    db_session.commit()

    dev = Device(name="r1-borda", management_address="10.0.0.1", credential_group_id=grupo.id)
    db_session.add(dev)
    db_session.commit()

    assert db_session.get(Device, dev.id).name == "r1-borda"
    assert db_session.get(CredentialGroup, grupo.id).vault_path.endswith("automacao")
