# Catálogo de coletores read-only. parser None = recurso bruto sem parse estruturado.
COLLECTORS: dict[str, dict] = {
    "version": {"commands": ["display version"], "parser": "version", "backup": False},
    "config_backup": {"commands": ["display current-configuration"], "parser": None, "backup": True},
}
