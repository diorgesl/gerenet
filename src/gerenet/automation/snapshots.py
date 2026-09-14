"""Leitura do texto da configuração salva num snapshot (spec §10).

O coletor `config_backup` grava o `display current-configuration` como arquivo
em disco e anota o caminho em `device_snapshots.raw_files`. Este módulo é o
único lugar que sabe abrir isso, para não haver duas versões do mesmo leitor.
"""
from pathlib import Path

from gerenet.domain import models


def texto_backup(snapshot: models.DeviceSnapshot | None) -> str:
    """Texto do `display current-configuration` salvo no snapshot (ou "")."""
    if snapshot is None:
        return ""
    arquivos = (snapshot.raw_files or {}).get("config_backup", [])
    if not arquivos:
        return ""
    try:
        return Path(str(arquivos[0])).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
