import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.services import users as svc


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _admin(db_session) -> None:
    svc.create_user(db_session, username="boss", password="senha-super-8", role="administrador", actor="cli")
    # create_user só faz flush: o login passa pela sessão do request, que não vê
    # transações não commitadas da fixture (padrão de _cria_usuario em test_auth_api).
    db_session.commit()


def _login(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json={"username": "boss", "password": "senha-super-8"})


def test_somente_admin_pode_listar(client: TestClient, db_session) -> None:
    assert client.get("/api/v1/users", headers=_auth()).status_code == 403
    svc.create_user(db_session, username="posse", password="senha-super-8", role="operador", actor="cli")
    db_session.commit()
    _admin(db_session)
    _login(client)
    lista = client.get("/api/v1/users").json()
    assert [u["username"] for u in lista] == ["boss", "posse"]
    assert "password_hash" not in lista[0]


def test_criar_audita_listar_com_include_disabled(client: TestClient, db_session) -> None:
    _admin(db_session)
    _login(client)
    resp = client.post(
        "/api/v1/users", json={"username": "vis3", "password": "senha-super-8", "role": "visualizador"}
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "visualizador"

    dup = client.post(
        "/api/v1/users", json={"username": "vis3", "password": "senha-super-8", "role": "visualizador"}
    )
    assert dup.status_code == 409

    curta = client.post(
        "/api/v1/users", json={"username": "curto4", "password": "123", "role": "operador"}
    )
    assert curta.status_code == 400

    dados = client.get("/api/v1/users").json()
    assert [u["username"] for u in dados] == ["boss", "vis3"]
    assert client.get("/api/v1/users?include_disabled=true").status_code == 200


def test_patch_regras(client: TestClient, db_session) -> None:
    _admin(db_session)
    _login(client)
    alvo = client.post(
        "/api/v1/users", json={"username": "ana", "password": "senha-super-8", "role": "operador"}
    ).json()
    uid = alvo["id"]

    resp = client.patch(f"/api/v1/users/{uid}", json={"role": "aprovador"})
    assert resp.status_code == 200 and resp.json()["role"] == "aprovador"

    assert client.patch("/api/v1/users/9999", json={"is_active": True}).status_code == 404

    outros = client.post(
        "/api/v1/users", json={"username": "bela", "password": "senha-super-8", "role": "operador"}
    ).json()
    assert client.patch(f"/api/v1/users/{outros['id']}", json={"username": "ana"}).status_code == 409


def test_nao_alterar_propria_conta(client: TestClient, db_session) -> None:
    _admin(db_session)
    _login(client)
    me = client.get("/api/v1/auth/me").json()
    resp = client.patch(f"/api/v1/users/{me['id']}", json={"role": "operador"})
    assert resp.status_code == 403
    assert "própria conta" in resp.json()["detail"]
    # username da própria conta é permitido
    assert client.patch(f"/api/v1/users/{me['id']}", json={"username": "boss2"}).status_code == 200


def test_reset_senha_invalida_antiga(client: TestClient, db_session) -> None:
    _admin(db_session)
    _login(client)
    alvo = client.post(
        "/api/v1/users", json={"username": "carol", "password": "senha-super-8", "role": "operador"}
    ).json()
    uid = alvo["id"]

    assert client.post(f"/api/v1/users/{uid}/password", json={"password": "nova-super-9"}).status_code == 204
    assert client.post(f"/api/v1/users/{uid}/password", json={"password": "curta"}).status_code == 400

    client.post("/api/v1/auth/logout")
    login = client.post("/api/v1/auth/login", json={"username": "carol", "password": "nova-super-9"})
    assert login.status_code == 200


def test_desativar_invalida_sessao(client: TestClient, db_session) -> None:
    _admin(db_session)
    client.post("/api/v1/auth/login", json={"username": "boss", "password": "senha-super-8"})
    operador = client.post(
        "/api/v1/users", json={"username": "diogo", "password": "senha-super-8", "role": "operador"}
    ).json()

    # diogo loga no próprio client só com cookie
    diogo = TestClient(create_app())
    diogo.post("/api/v1/auth/login", json={"username": "diogo", "password": "senha-super-8"})
    token = diogo.cookies.get("gerenet_sess")
    assert token is not None

    # admin desativa o diogo
    assert client.patch(f"/api/v1/users/{operador['id']}", json={"is_active": False}).status_code == 200

    # sessão existente do diogo passa a 403 (usuário desativado) e login novo → 401
    diogo.cookies.clear()
    diogo.cookies.set("gerenet_sess", token)
    # /users é o único router com require_actor no T4 (a troca dos demais é a T5)
    resp = diogo.get("/api/v1/users")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Usuário desativado."}
    # reativa para o "logon próprio" do bloco a seguir (autenticar rejeita inativo)
    assert client.patch(f"/api/v1/users/{operador['id']}", json={"is_active": True}).status_code == 200
    with TestClient(create_app()) as diogo:
        diogo.post("/api/v1/auth/login", json={"username": "diogo", "password": "senha-super-8"})
        token = diogo.cookies.get("gerenet_sess")
        assert token is not None

        assert client.patch(f"/api/v1/users/{operador['id']}", json={"is_active": False}).status_code == 200

        # o cookie do diogo (da sessão do logon próprio) agora é rejeitado
        resp = diogo.get("/api/v1/users")
        assert resp.status_code == 403
        assert resp.json() == {"detail": "Usuário desativado."}
        login = diogo.post("/api/v1/auth/login", json={"username": "diogo", "password": "senha-super-8"})
        assert login.status_code == 401
