"""Upstreams (§7) e communities de operadora (§7.1) — CLI na linha da casa (circuits.py)."""
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import UpstreamCommunityCreate, UpstreamCreate, UpstreamUpdate
from gerenet.domain.services import upstream_communities
from gerenet.domain.services import upstreams as svc
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.circuits import get_circuit, list_circuits
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Upstreams de trânsito/IX/PNI (§7).")
communities = typer.Typer(help="Communities de operadora por upstream (§7.1).")

_PAPEIS = ("principal", "contingencia")


def _resolver_upstream(session, upstream: str):
    """Upstream (ativo ou não) por ID ou nome; None se não existir."""
    if upstream.isdigit():
        try:
            return svc.get_upstream(session, int(upstream))
        except NotFoundError:
            return None
    return next(
        (u for u in svc.list_upstreams(session, include_disabled=True) if u.name == upstream),
        None,
    )


def _resolver_circuito(session, circuito: str):
    """Circuito (ativo ou não) por ID ou código; None se não existir."""
    if circuito.isdigit():
        try:
            return get_circuit(session, int(circuito))
        except NotFoundError:
            return None
    return next(
        (c for c in list_circuits(session, include_disabled=True) if c.code == circuito),
        None,
    )


@app.command("add")
def add(
    name: str = typer.Option(..., help="Nome único do upstream."),
    tipo: str = typer.Option(..., help="transito, ix, pni ou contingencia."),
    organization_id: int = typer.Option(..., "--organization-id", help="ID da organização operadora."),
    capacity: str | None = typer.Option(None, help="Capacidade (ex.: 10 Gbps)."),
    priority: int | None = typer.Option(None, help="Prioridade (1 = maior)."),
    cost: str | None = typer.Option(None, help="Custo (ex.: R$/Mbps)."),
    expected_prefixes_v4: int | None = typer.Option(None, "--expected-prefixes-v4", help="Prefixos v4 esperados."),
    expected_prefixes_v6: int | None = typer.Option(None, "--expected-prefixes-v6", help="Prefixos v6 esperados."),
    max_prefix_margin_pct: int = typer.Option(
        20, "--max-prefix-margin-pct", min=0, max=100, help="Margem do maximum-prefix (%)."
    ),
    rpki_enabled: bool = typer.Option(True, "--rpki-enabled/--no-rpki-enabled", help="Validação RPKI."),
    entrada_local_preference: int | None = typer.Option(None, "--entrada-local-preference", help="LP de entrada."),
    contingencia_local_preference: int | None = typer.Option(
        None, "--contingencia-local-preference", help="LP da contingência."
    ),
    contingencia_prepend: int | None = typer.Option(
        None, "--contingencia-prepend", min=0, max=10, help="Prepend da contingência (0-10)."
    ),
    contingencia_notes: str | None = typer.Option(None, "--contingencia-notes", help="Observações."),
) -> None:
    """Cadastra um upstream."""
    with get_session() as session:
        try:
            up = svc.create_upstream(
                session,
                UpstreamCreate(
                    name=name,
                    tipo=tipo,
                    organization_id=organization_id,
                    capacity=capacity,
                    priority=priority,
                    cost=cost,
                    expected_prefixes_v4=expected_prefixes_v4,
                    expected_prefixes_v6=expected_prefixes_v6,
                    max_prefix_margin_pct=max_prefix_margin_pct,
                    rpki_enabled=rpki_enabled,
                    entrada_local_preference=entrada_local_preference,
                    contingencia_local_preference=contingencia_local_preference,
                    contingencia_prepend=contingencia_prepend,
                    contingencia_notes=contingencia_notes,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Upstream {up.id} criado: {up.name} ({up.tipo})")


@app.command("list")
def listar(
    organization_id: int | None = typer.Option(None, "--organization-id", help="Filtra por organização."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista upstreams."""
    with get_session() as session:
        for up in svc.list_upstreams(session, organization_id=organization_id,
                                     include_disabled=include_disabled):
            typer.echo(
                f"{up.id:>4}  {up.name:<24} org {up.organization_id:>4} tipo {up.tipo:<12}"
            )


@app.command("show")
def show(upstream: str = typer.Argument(..., help="ID ou nome do upstream.")) -> None:
    """Mostra o detalhe: campos, circuitos vinculados, sessões e communities."""
    with get_session() as session:
        up = _resolver_upstream(session, upstream)
        if up is None:
            typer.echo("Upstream não encontrado.", err=True)
            raise typer.Exit(1)
        org = up.organization
        typer.echo(f"Upstream {up.id}: {up.name} ({up.tipo})")
        typer.echo(f"  organização  : {org.name if org else up.organization_id}")
        typer.echo(f"  capacidade   : {up.capacity or '-'}")
        typer.echo(f"  prioridade   : {up.priority if up.priority is not None else '-'}")
        typer.echo(f"  custo        : {up.cost or '-'}")
        typer.echo(
            f"  prefixos     : v4 {up.expected_prefixes_v4 or '-'} / v6 {up.expected_prefixes_v6 or '-'}"
            f" — margem {up.max_prefix_margin_pct}% — RPKI {'sim' if up.rpki_enabled else 'não'}"
        )
        typer.echo(
            f"  contingência : LP {up.contingencia_local_preference or '-'}"
            f" — prepend {up.contingencia_prepend or '-'}"
            f" — notas {up.contingencia_notes or '-'}"
        )
        typer.echo(f"  status       : {'ativo' if up.admin_status else 'desativado'}")
        typer.echo("  circuitos:")
        if up.circuitos:
            for v in up.circuitos:
                typer.echo(f"    {v.circuit_id:>4}  {v.circuito.code:<16} {v.papel:<12} ordem {v.ordem}")
        else:
            typer.echo("    (nenhum)")
        typer.echo("  sessões:")
        sessoes = [
            s for v in up.circuitos
            for s in list_sessions(session, circuit_id=v.circuit_id, include_disabled=False)
        ]
        if sessoes:
            for s in sessoes:
                typer.echo(f"    {s.id:>4}  {s.afi:<5} {s.local_address} → {s.remote_address}")
        else:
            typer.echo("    (nenhuma)")
        typer.echo("  communities:")
        coms = upstream_communities.list_upstream_communities(session, up.id)
        if coms:
            for uc_ in coms:
                typer.echo(
                    f"    {uc_.id:>4}  {uc_.value:<20} {uc_.purpose:<10} {uc_.direcao:<8}"
                    f" região {uc_.regiao or '-'}"
                )
        else:
            typer.echo("    (nenhuma)")


@app.command("update")
def atualizar(
    upstream: str = typer.Argument(..., help="ID ou nome do upstream."),
    name: str | None = typer.Option(None, "--name", help="Novo nome."),
    tipo: str | None = typer.Option(None, "--tipo", help="Novo tipo (transito, ix, pni ou contingencia)."),
    organization_id: int | None = typer.Option(None, "--organization-id", help="Nova organização operadora."),
    capacity: str | None = typer.Option(None, help="Nova capacidade."),
    priority: int | None = typer.Option(None, help="Nova prioridade (1 = maior)."),
    cost: str | None = typer.Option(None, help="Novo custo."),
    expected_prefixes_v4: int | None = typer.Option(None, "--expected-prefixes-v4", help="Prefixos v4 esperados."),
    expected_prefixes_v6: int | None = typer.Option(None, "--expected-prefixes-v6", help="Prefixos v6 esperados."),
    max_prefix_margin_pct: int | None = typer.Option(
        None, "--max-prefix-margin-pct", min=0, max=100, help="Margem do maximum-prefix (%)."
    ),
    rpki_enabled: bool | None = typer.Option(
        None, "--rpki-enabled/--no-rpki-enabled", help="Validação RPKI."
    ),
    entrada_local_preference: int | None = typer.Option(None, "--entrada-local-preference", help="LP de entrada."),
    contingencia_local_preference: int | None = typer.Option(
        None, "--contingencia-local-preference", help="LP da contingência."
    ),
    contingencia_prepend: int | None = typer.Option(
        None, "--contingencia-prepend", min=0, max=10, help="Prepend da contingência (0-10)."
    ),
    contingencia_notes: str | None = typer.Option(None, "--contingencia-notes", help="Observações."),
) -> None:
    """Atualiza campos do upstream (mudou o dataset ⇒ repropaga defaults às sessões)."""
    dados: dict = {}
    for campo, valor in (
        ("name", name),
        ("tipo", tipo),
        ("organization_id", organization_id),
        ("capacity", capacity),
        ("priority", priority),
        ("cost", cost),
        ("expected_prefixes_v4", expected_prefixes_v4),
        ("expected_prefixes_v6", expected_prefixes_v6),
        ("max_prefix_margin_pct", max_prefix_margin_pct),
        ("rpki_enabled", rpki_enabled),
        ("entrada_local_preference", entrada_local_preference),
        ("contingencia_local_preference", contingencia_local_preference),
        ("contingencia_prepend", contingencia_prepend),
        ("contingencia_notes", contingencia_notes),
    ):
        if valor is not None:
            dados[campo] = valor
    if not dados:
        typer.echo("Nenhum campo informado.", err=True)
        raise typer.Exit(1)
    with get_session() as session:
        up = _resolver_upstream(session, upstream)
        if up is None:
            typer.echo("Upstream não encontrado.", err=True)
            raise typer.Exit(1)
        try:
            atualizado = svc.update_upstream(session, up.id, UpstreamUpdate(**dados), actor="cli")
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Upstream {atualizado.id} atualizado: {atualizado.name}")


@app.command("disable")
def disable(upstream: str = typer.Argument(..., help="ID ou nome do upstream.")) -> None:
    """Desativa um upstream (mantém histórico e registro)."""
    with get_session() as session:
        up = _resolver_upstream(session, upstream)
        if up is None:
            typer.echo("Upstream não encontrado.", err=True)
            raise typer.Exit(1)
        svc.disable_upstream(session, up.id, actor="cli")
    typer.echo(f"Upstream {up.name} desativado.")


@app.command("circuit-add")
def circuit_add(
    upstream: str = typer.Argument(..., help="ID ou nome do upstream."),
    circuit: str = typer.Argument(..., help="ID ou código do circuito."),
    papel: str = typer.Option("principal", help="principal ou contingencia."),
    ordem: int = typer.Option(1, help="Ordem de preferência (1 = primeiro)."),
) -> None:
    """Vincula um circuito ao upstream (defaults caem nas sessões aqui)."""
    if papel not in _PAPEIS:
        typer.echo("Papel deve ser principal ou contingencia.", err=True)
        raise typer.Exit(1)
    with get_session() as session:
        up = _resolver_upstream(session, upstream)
        if up is None:
            typer.echo("Upstream não encontrado.", err=True)
            raise typer.Exit(1)
        circ = _resolver_circuito(session, circuit)
        if circ is None:
            typer.echo(f"Circuito {circuit} não encontrado.", err=True)
            raise typer.Exit(1)
        try:
            svc.vincular_circuito(session, up.id, circ.id, papel=papel, ordem=ordem, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Circuito {circ.code} vinculado ao upstream {up.name} ({papel}, ordem {ordem}).")


@app.command("circuit-rm")
def circuit_rm(
    upstream: str = typer.Argument(..., help="ID ou nome do upstream."),
    circuit: str = typer.Argument(..., help="ID ou código do circuito."),
) -> None:
    """Remove o vínculo circuito ↔ upstream (linha deletável; trilha na auditoria)."""
    with get_session() as session:
        up = _resolver_upstream(session, upstream)
        if up is None:
            typer.echo("Upstream não encontrado.", err=True)
            raise typer.Exit(1)
        circ = _resolver_circuito(session, circuit)
        if circ is None:
            typer.echo(f"Circuito {circuit} não encontrado.", err=True)
            raise typer.Exit(1)
        try:
            svc.desvincular_circuito(session, up.id, circ.id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Circuito {circ.code} desvinculado do upstream {up.name}.")


@communities.command("add")
def add_community(
    upstream_id: int = typer.Option(..., "--upstream-id", help="ID do upstream."),
    purpose: str = typer.Option(..., help="blackhole, prepend, lp ou info."),
    value: str = typer.Option(..., help="Valor concreto (ex.: 65530:20:0)."),
    direcao: str = typer.Option("ambos", help="import, export ou ambos."),
    regiao: str | None = typer.Option(None, "--regiao", help="Região da operadora."),
    bloquear: bool = typer.Option(False, "--bloquear", help="info → deny no import."),
    notes: str | None = typer.Option(None, help="Observações."),
) -> None:
    """Cadastra uma community de operadora com valor concreto."""
    with get_session() as session:
        try:
            uc_ = upstream_communities.add_upstream_community(
                session,
                upstream_id,
                UpstreamCommunityCreate(
                    purpose=purpose, value=value, direcao=direcao,
                    regiao=regiao, bloquear=bloquear, notes=notes,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Community {uc_.id} cadastrada no upstream {upstream_id}: {uc_.value} ({uc_.purpose})")


@communities.command("list")
def list_communities(
    upstream: str = typer.Argument(..., help="ID ou nome do upstream."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista as communities do upstream."""
    with get_session() as session:
        up = _resolver_upstream(session, upstream)
        if up is None:
            typer.echo("Upstream não encontrado.", err=True)
            raise typer.Exit(1)
        for uc_ in upstream_communities.list_upstream_communities(
            session, up.id, include_disabled=include_disabled
        ):
            typer.echo(
                f"{uc_.id:>4}  {uc_.value:<20} {uc_.purpose:<10} {uc_.direcao:<8}"
                f" região {uc_.regiao or '-'}"
            )


@communities.command("remove")
def remove_community(
    upstream: str = typer.Argument(..., help="ID ou nome do upstream."),
    community_id: int = typer.Argument(..., help="ID da community."),
) -> None:
    """Remove uma community de operadora (evento upstream_community.remove)."""
    with get_session() as session:
        up = _resolver_upstream(session, upstream)
        if up is None:
            typer.echo("Upstream não encontrado.", err=True)
            raise typer.Exit(1)
        try:
            upstream_communities.remove_upstream_community(session, up.id, community_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Community {community_id} removida do upstream {up.name}.")
