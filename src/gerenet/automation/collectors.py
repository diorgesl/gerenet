"""Read-only collector catalog (allowlist) and SoT-driven dynamic commands.

Each entry declares the commands to run and how to parse/merge them:
- `parser` (legacy): single command, single parse, first record as dict.
- `parser: None` (raw capture): no parse — the output is stored as-is
  (`config_backup`, `backup: True`).
- `parsers` + `merge`: one parser per command; `merge_parsed` combines rows
  into the resource shape (spec §4.3).
- `alvo_sessoes`: dynamic target — `comandos_verbose` derives the commands
  from the device's active BGP sessions in the Source of Truth.
"""
from sqlalchemy.orm import Session

from gerenet.domain.models import BgpSession

COLLECTORS = {
    "version": {"commands": ["display version"], "parser": "version", "backup": False},
    "config_backup": {"commands": ["display current-configuration"], "parser": None, "backup": True},
    "interfaces": {
        "commands": [
            "display interface brief",
            "display ip interface brief",
            "display ipv6 interface brief",
        ],
        "parsers": {
            "display interface brief": "int_brief",
            "display ip interface brief": "ip_int_brief",
            "display ipv6 interface brief": "ipv6_int_brief",
        },
        "merge": "interfaces",
    },
    "bgp_peers": {
        "commands": ["display bgp peer", "display bgp ipv6 peer"],
        "parsers": {"display bgp peer": "bgp_peer", "display bgp ipv6 peer": "bgp_peer"},
        "merge": "bgp_peers",
    },
    "bgp_peers_verbose": {
        "alvo_sessoes": True,
        "cap": 50,
        "parser_alvo": "bgp_peer_verbose",
        "merge": "bgp_peers_detalhes",
    },
}


def comandos_verbose(spec: dict, device_id: int, session: Session) -> list[str]:
    """One verbose command per active SoT session of the device (spec §4.1/§12).

    Sessions with admin_status on and shutdown off, ordered by afi then remote
    address, capped (the cap bounds cost per device). No sessions -> empty
    list: the runner skips the resource instead of failing the collection.
    """
    linhas = (
        session.query(BgpSession.afi, BgpSession.remote_address)
        .filter(
            BgpSession.device_id == device_id,
            BgpSession.admin_status.is_(True),
            BgpSession.shutdown.is_(False),
        )
        .distinct()
        .order_by(BgpSession.afi, BgpSession.remote_address)
        .limit(spec.get("cap", 50))
        .all()
    )
    return [
        f"display bgp {'ipv6 ' if afi == 'ipv6' else ''}peer {remoto} verbose"
        for afi, remoto in linhas
    ]
