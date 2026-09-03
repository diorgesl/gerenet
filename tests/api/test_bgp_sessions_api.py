import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session: Session) -> dict:
    """Org (ASN 64512), site, switch e 2 NE8000 (ASNs 64600/64601) no site."""
    site = create_site(db_session, SiteCreate(name="pop-bgp-api"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente BGP API", asn=64512), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-bgp-api", management_address="10.8.1.2"), actor="cli"
    )
    ne1 = create_device(
        db_session,
        DeviceCreate(name="ne8k-bgp-api1", management_address="10.8.1.1", asn=64600),
        actor="cli",
    )
    ne2 = create_device(
        db_session,
        DeviceCreate(name="ne8k-bgp-api2", management_address="10.8.1.3", asn=64601),
        actor="cli",
    )
    for dev in (sw, ne1, ne2):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne1_id": ne1.id, "ne2_id": ne2.id}


def _corpo_circuito(env: dict, code: str, *, edge: int | None = None) -> dict:
    return {
        "code": code,
        "organization_id": env["org_id"],
        "site_id": env["site_id"],
        "access_device_id": env["sw_id"],
        "access_port": "GE0/0/1",
        "edge_device_id": env["ne1_id"] if edge is None else edge,
    }


def _circuito(
    client: TestClient, env: dict, code: str, *, edge: int | None = None, **extra: object
) -> int:
    corpo = {**_corpo_circuito(env, code, edge=edge), **extra}
    resp = client.post("/api/v1/circuits", json=corpo, headers=_auth())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _sessao(
    client: TestClient, env: dict, circ_id: int,
    *, afi: str = "ipv4", local: str = "100.64.1.1", remote: str = "100.64.1.2",
    **extra: object,
) -> dict:
    corpo: dict[str, object] = {
        "circuit_id": circ_id,
        "device_id": env["ne1_id"],
        "afi": afi,
        "local_address": local,
        "remote_address": remote,
        **extra,
    }
    resp = client.post("/api/v1/bgp-sessions", json=corpo, headers=_auth())
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_cria_sessao_com_defaults_de_asn(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1001")
    corpo = _sessao(client, env, circ)
    assert corpo["asn_local"] == 64600  # default device.asn
    assert corpo["asn_remote"] == 64512  # default organization.asn
    assert corpo["has_password"] is False
    assert "password_ref" not in corpo

    corpo_v6 = _sessao(
        client, env, circ, afi="ipv6",
        local="2804:194C:1::1", remote="2804:194C:1::2",
        maximum_prefix=1000, shutdown=True,
    )
    assert corpo_v6["maximum_prefix"] == 1000


def test_cria_com_perfil_e_valida_direcao(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    export = list_policy_profiles(db_session, direction="export")[0]
    circ = _circuito(client, env, "CIRC-1002")
    corpo = _sessao(client, env, circ, export_profile_id=export.id)
    assert corpo["export_profile_id"] == export.id

    errado = client.post(
        "/api/v1/bgp-sessions",
        json={
            "circuit_id": circ, "device_id": env["ne1_id"], "afi": "ipv4",
            "local_address": "100.64.2.1", "remote_address": "100.64.2.2",
            "import_profile_id": export.id,  # direção errada
        },
        headers=_auth(),
    )
    assert errado.status_code == 400
    assert "direção" in errado.json()["detail"] or "direcao" in errado.json()["detail"]


def test_erros_de_criacao(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1003")
    _sessao(client, env, circ, local="100.64.3.1", remote="100.64.3.2")

    # mesmo (device, VRF, afi): 409
    dup = client.post(
        "/api/v1/bgp-sessions",
        json={
            "circuit_id": circ, "device_id": env["ne1_id"], "afi": "ipv4",
            "local_address": "100.64.3.3", "remote_address": "100.64.3.4",
        },
        headers=_auth(),
    )
    assert dup.status_code == 409

    # device fora do circuito: 400
    circ2 = _circuito(client, env, "CIRC-1004", edge=env["ne2_id"])
    fora = client.post(
        "/api/v1/bgp-sessions",
        json={
            "circuit_id": circ2, "device_id": env["ne1_id"], "afi": "ipv4",
            "local_address": "100.64.4.1", "remote_address": "100.64.4.2",
        },
        headers=_auth(),
    )
    assert fora.status_code == 400
    assert "edge/backup_edge" in fora.json()["detail"]

    # endereço da família errada: 400
    ruim = client.post(
        "/api/v1/bgp-sessions",
        json={
            "circuit_id": circ2, "device_id": env["ne2_id"], "afi": "ipv4",
            "local_address": "2804::1", "remote_address": "100.64.4.2",
        },
        headers=_auth(),
    )
    assert ruim.status_code == 400

    assert client.get("/api/v1/bgp-sessions/9999", headers=_auth()).status_code == 404


def test_lista_filtra_por_circuito_e_device(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1005")
    _sessao(client, env, circ)
    lista = client.get(f"/api/v1/bgp-sessions?circuit_id={circ}", headers=_auth()).json()
    assert len(lista) == 1
    assert client.get(f"/api/v1/bgp-sessions?device_id={env['ne2_id']}", headers=_auth()).json() == []


def test_patch_desativa_e_guarda_asn_remote(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1006")
    corpo = _sessao(client, env, circ)
    sessao_id = corpo["id"]

    off = client.patch(f"/api/v1/bgp-sessions/{sessao_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False
    assert off.json()["has_password"] is False

    # _ambiente audita também site/org/devices — filtro espelha o padrão dos
    # testes de domínio (só eventos de circuito e de sessão BGP).
    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        if e.type.startswith(("circuit.", "bgp_session."))
    ]
    assert tipos == ["circuit.create", "bgp_session.create", "bgp_session.disable"]

    # trocar para organização sem ASN sem asn_remote: 400 (ruling 8)
    org_sem = create_organization(
        db_session, OrganizationCreate(name="Cliente BGP Sem ASN"), actor="cli"
    )
    circ2 = _circuito(client, env, "CIRC-1007", organization_id=org_sem.id)
    sem_asn = client.patch(
        f"/api/v1/bgp-sessions/{sessao_id}", json={"circuit_id": circ2}, headers=_auth()
    )
    assert sem_asn.status_code == 400
    assert "asn_remote" in sem_asn.json()["detail"]

    com_asn = client.patch(
        f"/api/v1/bgp-sessions/{sessao_id}",
        json={"circuit_id": circ2, "asn_remote": 64530},
        headers=_auth(),
    )
    assert com_asn.status_code == 200
    assert com_asn.json()["asn_remote"] == 64530


def test_password_set_grava_vault_e_audita(client: TestClient, db_session: Session) -> None:
    from gerenet.config import Settings
    from gerenet.secrets.vault_store import VaultSecretStore

    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1008")
    sessao_id = _sessao(client, env, circ)["id"]

    resp = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/password",
        json={"password": "md5-api-segredo"},
        headers=_auth(),
    )
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["has_password"] is True
    assert "password_ref" not in corpo

    sessao_db = db_session.get(models.BgpSession, sessao_id)
    assert sessao_db is not None
    caminho = sessao_db.password_ref
    assert caminho == f"gerenet/bgp-sessions/{sessao_id}/password"

    settings = Settings(_env_file=None)
    store = VaultSecretStore(settings.vault_url, settings.vault_token)
    assert store.get_secret(caminho) == {"password": "md5-api-segredo"}

    # _ambiente audita também site/org/devices — filtro espelha o padrão dos
    # testes de domínio (só eventos de circuito e de sessão BGP).
    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        if e.type.startswith(("circuit.", "bgp_session."))
    ]
    assert tipos == ["circuit.create", "bgp_session.create", "bgp_session.password_set"]
    # nenhum evento carrega o valor da senha
    for evento in db_session.scalars(select(models.AuditEvent)):
        assert "md5-api-segredo" not in str(evento.details)


def test_password_set_vault_fora_do_ar_da_503(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gerenet.api.routers import bgp_sessions as modulo

    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1009")
    sessao_id = _sessao(client, env, circ)["id"]

    def _falha(*args: object, **kwargs: object) -> None:
        raise RuntimeError("conexão recusada")

    monkeypatch.setattr(modulo, "VaultSecretStore", _falha)
    resp = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/password",
        json={"password": "md5-x"},
        headers=_auth(),
    )
    assert resp.status_code == 503
    assert "Vault indisponível" in resp.json()["detail"]

    assert client.post(
        "/api/v1/bgp-sessions/9999/password", json={"password": "md5-x"}, headers=_auth()
    ).status_code == 404
