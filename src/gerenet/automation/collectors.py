"""Read-only collector catalog (allowlist).

Each entry declares the commands to run and how to parse/merge them:
- `parser` (legacy): single command, single parse, first record as dict.
- `parsers` + `merge`: one parser per command; `merge_parsed` combines rows
  into the resource shape (spec §4.3).
"""

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
}
