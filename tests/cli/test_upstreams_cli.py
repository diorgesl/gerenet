"""CLI de upstreams e upstream-communities (fase 5 — §7/§7.1): CliRunner + DB real.

Molde: tests/cli/test_mpls_cli.py e test_cli_smoke.py — invoca o app completo
(gera os grupos no caminho `upstreams ...`), banco real da suíte
(GERENET_DATABASE_URL apontado para o banco de teste em tests/conftest.py) e
fixtures compartilhadas da fase 5 (org_operadora, up, circuito_up).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain import models

runner = CliRunner()


def test_cli_upstreams_add_list_show_disable(db_session: Session, org_operadora: models.Organization) -> None:
    add = runner.invoke(
        app,
        [
            "upstreams", "add",
            "--name", "cli-up", "--tipo", "transito",
            "--organization-id", str(org_operadora.id),
            "--expected-prefixes-v4", "1000",
            "--max-prefix-margin-pct", "10",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "criado" in add.output and "cli-up" in add.output

    lista = runner.invoke(app, ["upstreams", "list"])
    assert lista.exit_code == 0, lista.output
    assert "cli-up" in lista.output

    show = runner.invoke(app, ["upstreams", "show", "cli-up"])
    assert show.exit_code == 0, show.output
    assert "cli-up" in show.output and "transito" in show.output
    assert "1000" in show.output

    off = runner.invoke(app, ["upstreams", "disable", "cli-up"])
    assert off.exit_code == 0, off.output
    assert "desativado" in off.output

    assert "cli-up" not in runner.invoke(app, ["upstreams", "list"]).output
    assert "cli-up" in runner.invoke(app, ["upstreams", "list", "--all"]).output


def test_cli_upstreams_erros(db_session: Session, org_operadora: models.Organization,
                             org_downstream: models.Organization) -> None:
    primeiro = runner.invoke(app, [
        "upstreams", "add", "--name", "cli-up-dup", "--tipo", "ix",
        "--organization-id", str(org_operadora.id),
    ])
    assert primeiro.exit_code == 0, primeiro.output

    duplicado = runner.invoke(app, [
        "upstreams", "add", "--name", "cli-up-dup", "--tipo", "ix",
        "--organization-id", str(org_operadora.id),
    ])
    assert duplicado.exit_code == 1
    assert "Erro:" in duplicado.output and "Já existe" in duplicado.output

    nao_operadora = runner.invoke(app, [
        "upstreams", "add", "--name", "cli-up-org", "--tipo", "ix",
        "--organization-id", str(org_downstream.id),
    ])
    assert nao_operadora.exit_code == 1
    assert "Erro:" in nao_operadora.output and "operadora" in nao_operadora.output

    tipo_invalido = runner.invoke(app, [
        "upstreams", "add", "--name", "cli-up-tipo", "--tipo", "p2p",
        "--organization-id", str(org_operadora.id),
    ])
    assert tipo_invalido.exit_code == 1
    assert "Erro:" in tipo_invalido.output

    faltante = runner.invoke(app, ["upstreams", "disable", "nao-existe"])
    assert faltante.exit_code == 1
    assert "não encontrado" in faltante.output


def test_cli_upstreams_update(db_session: Session, org_operadora: models.Organization) -> None:
    add = runner.invoke(app, [
        "upstreams", "add", "--name", "cli-up-upd", "--tipo", "ix",
        "--organization-id", str(org_operadora.id),
    ])
    assert add.exit_code == 0, add.output

    r = runner.invoke(app, [
        "upstreams", "update", "cli-up-upd",
        "--expected-prefixes-v4", "2000",
        "--no-rpki-enabled",
        "--entrada-local-preference", "90",
    ])
    assert r.exit_code == 0, r.output
    assert "atualizado" in r.output

    db_session.expire_all()  # CLI grava em outra sessão; expira antes de reler
    up = db_session.scalar(select(models.Upstream).where(models.Upstream.name == "cli-up-upd"))
    assert up is not None
    assert up.expected_prefixes_v4 == 2000
    assert up.rpki_enabled is False
    assert up.entrada_local_preference == 90

    sem_opcoes = runner.invoke(app, ["upstreams", "update", "cli-up-upd"])
    assert sem_opcoes.exit_code == 1
    assert "Nenhum campo informado." in sem_opcoes.output

    inexistente = runner.invoke(app, ["upstreams", "update", "nao-existe", "--capacity", "10 Gbps"])
    assert inexistente.exit_code == 1
    assert "não encontrado" in inexistente.output


def test_cli_upstreams_circuit_add_remove(db_session: Session, up: models.Upstream,
                                          circuito_up: models.Circuit) -> None:
    vincula = runner.invoke(app, [
        "upstreams", "circuit-add", "transito-f5", "CIRC-UP-0001",
        "--papel", "principal", "--ordem", "2",
    ])
    assert vincula.exit_code == 0, vincula.output
    assert "vinculado" in vincula.output and "CIRC-UP-0001" in vincula.output

    vinculo = db_session.scalar(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.circuit_id == circuito_up.id))
    assert vinculo is not None
    assert vinculo.papel == "principal" and vinculo.ordem == 2

    de_novo = runner.invoke(app, [
        "upstreams", "circuit-add", "transito-f5", "CIRC-UP-0001",
        "--papel", "contingencia", "--ordem", "3",
    ])
    assert de_novo.exit_code == 1
    assert "Erro:" in de_novo.output

    desvincula = runner.invoke(app, ["upstreams", "circuit-rm", "transito-f5", "CIRC-UP-0001"])
    assert desvincula.exit_code == 0, desvincula.output
    assert "desvinculado" in desvincula.output
    assert db_session.scalar(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.circuit_id == circuito_up.id)) is None


def test_cli_upstream_communities_add_list_remove(db_session: Session, up: models.Upstream) -> None:
    add = runner.invoke(app, [
        "upstream-communities", "add",
        "--upstream-id", str(up.id),
        "--purpose", "blackhole",
        "--value", "65530:20:0",
        "--direcao", "import",
        "--regiao", "nordeste",
        "--bloquear",
    ])
    assert add.exit_code == 0, add.output
    assert "cadastrada" in add.output and "65530:20:0" in add.output

    lista = runner.invoke(app, ["upstream-communities", "list", "transito-f5"])
    assert lista.exit_code == 0, lista.output
    assert "65530:20:0" in lista.output and "blackhole" in lista.output

    uc_id = db_session.scalar(
        select(models.UpstreamCommunity.id).where(
            models.UpstreamCommunity.upstream_id == up.id,
            models.UpstreamCommunity.value == "65530:20:0",
        ))
    assert uc_id is not None

    duplicada = runner.invoke(app, [
        "upstream-communities", "add",
        "--upstream-id", str(up.id),
        "--purpose", "blackhole", "--value", "65530:20:0", "--regiao", "nordeste",
    ])
    assert duplicada.exit_code == 1
    assert "Erro:" in duplicada.output and "já cadastrada" in duplicada.output

    sem_upstream = runner.invoke(app, [
        "upstream-communities", "add",
        "--upstream-id", "99999",
        "--purpose", "blackhole", "--value", "65530:21:0",
    ])
    assert sem_upstream.exit_code == 1
    assert "não encontrado" in sem_upstream.output

    remove = runner.invoke(app, ["upstream-communities", "remove", "transito-f5", str(uc_id)])
    assert remove.exit_code == 0, remove.output
    assert "removida" in remove.output
    assert db_session.scalar(
        select(models.UpstreamCommunity).where(models.UpstreamCommunity.id == uc_id)) is None

    removida_de_novo = runner.invoke(app, ["upstream-communities", "remove", "transito-f5", str(uc_id)])
    assert removida_de_novo.exit_code == 1
    assert "não encontrada" in removida_de_novo.output
