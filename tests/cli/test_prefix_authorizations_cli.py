"""CLI de autorizações de prefixo — origem manual/IRR/RPKI (§6.4/§10.4, F5 E3).

Padrão dos vizinhos (`tests/cli/test_cli_ops.py`): `CliRunner` do typer sobre
o app do `gerenet.cli.main`; a fixture `db_session` usa o mesmo banco do
conftest (var de ambiente já apontada para o banco de teste)."""
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain.schemas import OrganizationCreate
from gerenet.domain.services.organizations import create_organization

runner = CliRunner()


def test_cli_add_origin_rpki_e_lista_exibe_origem_validacao(db_session: Session) -> None:
    """`add --origin rpki` cria com `nao_verificada` e o `list` imprime
    origem e validação na linha (modo linha atualizado)."""
    org = create_organization(
        db_session, OrganizationCreate(name="Org do CLI", asn=64512), actor="cli"
    )

    adiciona = runner.invoke(
        app,
        [
            "prefix-authorizations",
            "add",
            "--organization-id",
            str(org.id),
            "--family",
            "ipv4",
            "--prefix",
            "200.160.0.0/22",
            "--origin",
            "rpki",
        ],
    )
    assert adiciona.exit_code == 0, adiciona.output

    lista = runner.invoke(app, ["prefix-authorizations", "list"])
    assert lista.exit_code == 0, lista.output
    assert "rpki" in lista.output
    assert "nao_verificada" in lista.output


def test_cli_add_origin_invalida_rejeitada(db_session: Session) -> None:
    """Origem fora do enum manual|irr|rpki ⇒ erro de schema (exit 1)."""
    org = create_organization(
        db_session, OrganizationCreate(name="Org do CLI 2", asn=64513), actor="cli"
    )

    adiciona = runner.invoke(
        app,
        [
            "prefix-authorizations",
            "add",
            "--organization-id",
            str(org.id),
            "--family",
            "ipv4",
            "--prefix",
            "200.161.0.0/22",
            "--origin",
            "on-prem",
        ],
    )
    assert adiciona.exit_code == 1
    assert "Erro:" in adiciona.output
