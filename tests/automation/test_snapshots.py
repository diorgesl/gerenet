"""Leitura do texto da configuração salva num snapshot (spec §10)."""
from pathlib import Path

from gerenet.automation.snapshots import texto_backup
from gerenet.domain import models


def _snapshot(db_session, device, raw_files) -> models.DeviceSnapshot:
    snap = models.DeviceSnapshot(device_id=device.id, status="success", raw_files=raw_files)
    db_session.add(snap)
    db_session.commit()
    return snap


def test_snapshot_nulo_devolve_vazio() -> None:
    assert texto_backup(None) == ""


def test_sem_recurso_de_backup_devolve_vazio(db_session, edge_device) -> None:
    snap = _snapshot(db_session, edge_device, {"interfaces": []})
    assert texto_backup(snap) == ""


def test_arquivo_ausente_devolve_vazio(db_session, edge_device, tmp_path: Path) -> None:
    snap = _snapshot(db_session, edge_device, {"config_backup": [str(tmp_path / "nao-existe.txt")]})
    assert texto_backup(snap) == ""


def test_le_o_conteudo_do_arquivo(db_session, edge_device, tmp_path: Path) -> None:
    arquivo = tmp_path / "current.txt"
    arquivo.write_text("sysname NE8000\n#\n", encoding="utf-8")
    snap = _snapshot(db_session, edge_device, {"config_backup": [str(arquivo)]})
    assert texto_backup(snap) == "sysname NE8000\n#\n"
