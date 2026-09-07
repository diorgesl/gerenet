"""MPLS em switches no CLI (spec §9): domínios, L2VC e VSI.

`gerenet mpls` vira `mpls domain ...` / `mpls l2vc ...` / `mpls vsi ...`
via `add_typer` no próprio arquivo; `cli/main.py` registra só o grupo raiz.
"""
from typing import Literal

import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.automation import l2vc as l2vc_auto
from gerenet.db import get_session
from gerenet.domain.schemas import L2vcCreate, L2vcEndpointIn, MplsDomainCreate, MplsMemberIn
from gerenet.domain.services import mpls as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(no_args_is_help=True, help="MPLS em switches (domínios, L2VC, VSI).")
domain_app = typer.Typer(no_args_is_help=True, help="Domínios MPLS.")
l2vc_app = typer.Typer(no_args_is_help=True, help="Serviços L2VC.")
vsi_app = typer.Typer(no_args_is_help=True, help="Serviços VSI (consulta).")
app.add_typer(domain_app, name="domain")
app.add_typer(l2vc_app, name="l2vc")
app.add_typer(vsi_app, name="vsi")


@domain_app.command("add")
def domain_add(
    name: str = typer.Option(..., help="Nome do domínio MPLS."),
    description: str | None = typer.Option(None, help="Descrição."),
) -> None:
    """Cadastra um domínio MPLS."""
    with get_session() as session:
        try:
            dom = svc.create_domain(
                session, MplsDomainCreate(name=name, description=description), actor="cli"
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Domínio #{dom.id} criado: {dom.name}")


@domain_app.command("list")
def domain_list(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista domínios MPLS."""
    with get_session() as session:
        for dom in svc.list_domains(session, include_disabled=include_disabled):
            n = len(dom.members)
            typer.echo(
                f"{dom.id:>3}  {dom.name:<20} "
                f"{'desativado' if not dom.admin_status else 'ativo':<10} {n} membro(s)"
            )


@domain_app.command("add-member")
def domain_add_member(
    domain_id: int = typer.Option(..., "--domain-id", help="ID do domínio."),
    device_id: int = typer.Option(..., "--device-id", help="ID do equipamento (PE)."),
    loopback: str = typer.Option(..., "--loopback", help="Loopback LDP."),
    role: Literal["pe", "core"] = typer.Option("pe", help="pe ou core."),
) -> None:
    """Adiciona um equipamento ao domínio."""
    with get_session() as session:
        try:
            membro = svc.add_domain_member(
                session, domain_id,
                MplsMemberIn(device_id=device_id, loopback_address=loopback, role=role),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"{membro.device_id} adicionado ao domínio #{domain_id} (loopback {loopback}).")


@domain_app.command("remove-member")
def domain_remove_member(
    domain_id: int = typer.Option(..., "--domain-id", help="ID do domínio."),
    device_id: int = typer.Option(..., "--device-id", help="ID do equipamento."),
) -> None:
    """Remove um equipamento do domínio."""
    with get_session() as session:
        try:
            svc.remove_domain_member(session, domain_id, device_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"{device_id} removido do domínio #{domain_id}.")


@l2vc_app.command("add")
def l2vc_add(
    domain_id: int = typer.Option(..., "--domain-id", help="ID do domínio MPLS."),
    name: str = typer.Option(..., help="Nome lógico do serviço."),
    vc_id: int | None = typer.Option(None, "--vc-id", help="VC-ID (default: próximo livre do domínio)."),
    device_a: int = typer.Option(..., "--device-a", help="ID do switch da ponta A."),
    interface_a: str = typer.Option(..., "--interface-a", help="Interface de acesso (ex.: 10GE0/0/1)."),
    vid_a: int = typer.Option(..., "--vid-a", help="VLAN de acesso da ponta A."),
    device_b: int = typer.Option(..., "--device-b", help="ID do switch da ponta B."),
    interface_b: str = typer.Option(..., "--interface-b", help="Interface de acesso (ex.: 10GE0/0/2)."),
    vid_b: int = typer.Option(..., "--vid-b", help="VLAN de acesso da ponta B."),
    encap: Literal["dot1q", "qinq"] = typer.Option("dot1q", help="dot1q ou qinq."),
    inner_vlan_a: int | None = typer.Option(None, "--inner-vlan-a", help="VLAN interna da ponta A (qinq)."),
    inner_vlan_b: int | None = typer.Option(None, "--inner-vlan-b", help="VLAN interna da ponta B (qinq)."),
    mtu: int = typer.Option(1500, "--mtu", min=1500, max=9216, help="MTU do L2VC."),
    control_word: bool = typer.Option(False, "--control-word", help="Habilita control-word."),
    flow_label: bool = typer.Option(
        False, "--flow-label", help="Habilita flow-label (requer 'mpls_flow_label' na capability)."
    ),
    organization_id: int | None = typer.Option(None, "--organization-id", help="Organização (opcional)."),
) -> None:
    """Cadastra um serviço L2VC entre duas pontas."""
    with get_session() as session:
        try:
            servico = svc.create_l2vc(
                session,
                L2vcCreate(
                    domain_id=domain_id, name=name, vc_id=vc_id, organization_id=organization_id,
                    mtu=mtu, control_word=control_word, flow_label=flow_label,
                    endpoints=[
                        L2vcEndpointIn(
                            device_id=device_a, interface=interface_a, encapsulation=encap,
                            vid=vid_a, inner_vlan=inner_vlan_a, mtu=mtu,
                        ),
                        L2vcEndpointIn(
                            device_id=device_b, interface=interface_b, encapsulation=encap,
                            vid=vid_b, inner_vlan=inner_vlan_b, mtu=mtu,
                        ),
                    ],
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"L2VC #{servico.id} criado: {servico.name} (VC-ID {servico.vc_id})")


@l2vc_app.command("list")
def l2vc_list(
    domain_id: int | None = typer.Option(None, "--domain-id", help="Filtra por domínio."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista serviços L2VC."""
    with get_session() as session:
        for servico in svc.list_l2vc(session, domain_id=domain_id, include_disabled=include_disabled):
            estado = "desativado" if not servico.admin_status else servico.operational_status
            typer.echo(f"{servico.id:>3}  {servico.name:<24} vc {servico.vc_id:>5}  {estado}")


@l2vc_app.command("show")
def l2vc_show(l2vc_id: int = typer.Argument(..., help="ID do L2VC.")) -> None:
    """Mostra um L2VC: pontas e parâmetros."""
    with get_session() as session:
        try:
            servico = svc.get_l2vc(session, l2vc_id)
        except NotFoundError as exc:
            typer.echo(f"L2VC não encontrado: {l2vc_id}.", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"L2VC #{servico.id}: {servico.name} — VC-ID {servico.vc_id} ({servico.operational_status})")
        typer.echo(
            f"  mtu {servico.mtu} | control-word {'sim' if servico.control_word else 'não'} "
            f"| flow-label {'sim' if servico.flow_label else 'não'}"
        )
        for ep in servico.endpoints:
            typer.echo(f"  ponta device {ep.device_id}: {ep.interface} ({ep.encapsulation})")


@l2vc_app.command("set-status")
def l2vc_set_status(
    l2vc_id: int = typer.Argument(..., help="ID do L2VC."),
    ativo: bool = typer.Option(True, "--ativo/--inativo", help="Ativa (default) ou desativa o serviço."),
) -> None:
    """Reativa ou desativa um serviço L2VC."""
    with get_session() as session:
        try:
            servico = svc.set_l2vc_status(session, l2vc_id, admin_status=ativo, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"L2VC #{servico.id} {'ativado' if ativo else 'desativado'}.")


@l2vc_app.command("plano")
def l2vc_plano(l2vc_id: int = typer.Argument(..., help="ID do L2VC.")) -> None:
    """Mostra o plano de provision por ponta (sem executar)."""
    with get_session() as session:
        try:
            servico = svc.get_l2vc(session, l2vc_id)
        except NotFoundError as exc:
            typer.echo(f"L2VC não encontrado: {l2vc_id}.", err=True)
            raise typer.Exit(1) from exc
        for item in l2vc_auto.plan_provision_l2vc(session, servico):
            typer.echo(f"ponta device {item.device_id}: {len(item.blocos)} bloco(s)")
            for bloco in item.blocos:
                primeiro = bloco["comandos"][0] if bloco["comandos"] else "(sem comandos)"
                typer.echo(f"  {bloco['tipo']} {bloco['acao']}: {primeiro}")
            if item.aviso:
                typer.echo(f"  aviso: {item.aviso}")


@vsi_app.command("list")
def vsi_list(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista serviços VSI (consulta)."""
    with get_session() as session:
        for servico in svc.list_vsi(session, include_disabled=include_disabled):
            typer.echo(
                f"{servico.id:>3}  {servico.name:<24} vsi {servico.vsi_id:>5}  {servico.vrp_name}"
            )


@vsi_app.command("show")
def vsi_show(vsi_id: int = typer.Argument(..., help="ID do VSI.")) -> None:
    """Mostra um VSI: parâmetros e membros."""
    with get_session() as session:
        try:
            servico = svc.get_vsi(session, vsi_id)
        except NotFoundError as exc:
            typer.echo(f"VSI não encontrado: {vsi_id}.", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"VSI #{servico.id}: {servico.name} ({servico.vrp_name}) — {servico.operational_status}")
        typer.echo(
            f"  mtu {servico.mtu} | split-horizon {'sim' if servico.split_horizon else 'não'} "
            f"| mac-limit {servico.mac_limit}"
        )
        for m in servico.members:
            typer.echo(f"  membro device {m.device_id}")
