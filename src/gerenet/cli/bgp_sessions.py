import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.config import get_settings
from gerenet.db import get_session
from gerenet.domain.schemas import BgpSessionCreate
from gerenet.domain.services import bgp_sessions as svc
from gerenet.domain.services.errors import GerenetError
from gerenet.secrets.vault_store import VaultSecretStore

app = typer.Typer(help="Sessões BGP por família.")
password = typer.Typer(help="Senha MD5 do peer (valor só no Vault).")
app.add_typer(password, name="password")


@app.command("add")
def add(
    circuit_id: int = typer.Option(..., "--circuit-id", help="ID do circuito."),
    device_id: int = typer.Option(..., "--device-id", help="ID do edge (NE8000)."),
    afi: str = typer.Option(..., help="ipv4 ou ipv6."),
    local_address: str = typer.Option(..., "--local-address", help="Endereço local."),
    remote_address: str = typer.Option(..., "--remote-address", help="Endereço remoto."),
    source_address: str | None = typer.Option(None, "--source-address", help="Source address (opcional)."),
    asn_local: int | None = typer.Option(
        None, "--asn-local", min=1, max=4294967295,
        help="ASN local (default: ASN do equipamento).",
    ),
    asn_remote: int | None = typer.Option(
        None, "--asn-remote", min=1, max=4294967295,
        help="ASN remoto (default: ASN da organização).",
    ),
    description: str | None = typer.Option(None, help="Descrição."),
    import_profile_id: int | None = typer.Option(None, "--import-profile-id", help="Perfil de importação."),
    export_profile_id: int | None = typer.Option(None, "--export-profile-id", help="Perfil de exportação."),
    maximum_prefix: int | None = typer.Option(None, "--maximum-prefix", help="Limite de prefixos."),
    maximum_prefix_threshold: int | None = typer.Option(
        None, "--maximum-prefix-threshold", min=0, max=100, help="Limiar em % (0-100)."
    ),
    local_preference: int | None = typer.Option(None, "--local-preference", help="Local preference."),
    med: int | None = typer.Option(None, help="MED."),
    prepend: int | None = typer.Option(None, min=0, max=10, help="Prepend (0-10)."),
    keepalive: int | None = typer.Option(None, help="Timer keepalive (s)."),
    holdtime: int | None = typer.Option(None, help="Timer holdtime (s)."),
    bfd_enabled: bool = typer.Option(False, "--bfd-enabled", help="Habilita BFD."),
    graceful_restart: bool = typer.Option(False, "--graceful-restart", help="Graceful restart."),
    shutdown: bool = typer.Option(False, "--shutdown", help="Admin shutdown."),
    allow_default_route: bool = typer.Option(False, "--allow-default-route", help="Aceita rota default."),
) -> None:
    """Cadastra uma sessão BGP."""
    with get_session() as session:
        try:
            sessao = svc.create_session(
                session,
                BgpSessionCreate(
                    circuit_id=circuit_id,
                    device_id=device_id,
                    afi=afi,
                    local_address=local_address,
                    remote_address=remote_address,
                    source_address=source_address,
                    asn_local=asn_local,
                    asn_remote=asn_remote,
                    description=description,
                    import_profile_id=import_profile_id,
                    export_profile_id=export_profile_id,
                    maximum_prefix=maximum_prefix,
                    maximum_prefix_threshold=maximum_prefix_threshold,
                    local_preference=local_preference,
                    med=med,
                    prepend=prepend,
                    keepalive=keepalive,
                    holdtime=holdtime,
                    bfd_enabled=bfd_enabled,
                    graceful_restart=graceful_restart,
                    shutdown=shutdown,
                    allow_default_route=allow_default_route,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Sessão BGP {sessao.id} criada: {sessao.afi} {sessao.local_address} → {sessao.remote_address}")


@app.command("list")
def listar(
    circuit_id: int | None = typer.Option(None, "--circuit-id", help="Filtra por circuito."),
    device_id: int | None = typer.Option(None, "--device-id", help="Filtra por equipamento."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista sessões BGP."""
    with get_session() as session:
        for sessao in svc.list_sessions(
            session, circuit_id=circuit_id, device_id=device_id,
            include_disabled=include_disabled,
        ):
            typer.echo(
                f"{sessao.id:>4}  {sessao.afi:<4} {sessao.local_address:<16} → "
                f"{sessao.remote_address:<16} circ {sessao.circuit_id:>4}"
            )


@app.command("disable")
def disable(session_id: int = typer.Argument(..., help="ID da sessão BGP.")) -> None:
    """Desativa uma sessão (mantém histórico e registro)."""
    with get_session() as session:
        try:
            svc.disable_session(session, session_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Sessão BGP {session_id} desativada.")


@password.command("set")
def definir_senha(
    session_id: int = typer.Argument(..., help="ID da sessão BGP."),
    password: str = typer.Option(
        ...,
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Senha MD5 do peer (valor só no Vault).",
    ),
) -> None:
    """Define/troca a senha MD5 da sessão — o valor fica apenas no Vault."""
    with get_session() as session:
        try:
            sessao = svc.get_session(session, session_id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        caminho = f"gerenet/bgp-sessions/{sessao.id}/password"
        try:
            settings = get_settings()
            store = VaultSecretStore(settings.vault_url, settings.vault_token)
            store.set_secret(caminho, {"password": password})
        except RuntimeError as exc:
            typer.echo(f"Erro: Vault indisponível: {exc}", err=True)
            raise typer.Exit(1) from exc
        svc.set_password(session, sessao.id, actor="cli", path=caminho)
    typer.echo(f"Senha definida para a sessão BGP {sessao.id} (armazenada no Vault).")
