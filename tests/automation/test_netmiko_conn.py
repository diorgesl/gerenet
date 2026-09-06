import base64
import hashlib
from unittest.mock import MagicMock

import pytest

from gerenet.automation.netmiko_conn import (
    CommandNotAllowed,
    ConfigNotAllowed,
    ConnectionFailed,
    HostKeyMismatch,
    connect_and_apply,
    connect_and_run,
)
from gerenet.config import Settings

SETTINGS = Settings(_env_file=None)


def _fingerprint_de(bytes_chave: bytes) -> str:
    b64 = base64.b64encode(hashlib.sha256(bytes_chave).digest()).decode()
    return f"sha256:{b64}"


def _conexao_fake() -> MagicMock:
    conn = MagicMock()
    chave = MagicMock()
    chave.asbytes.return_value = b"chave-de-teste"
    conn.remote_conn.transport.get_remote_server_key.return_value = chave
    return conn


def test_recusa_comando_fora_da_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = MagicMock(return_value=_conexao_fake())
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", handler)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    with pytest.raises(CommandNotAllowed):
        connect_and_run(dev, "u", "p", ["configure terminal"], SETTINGS)
    handler.assert_not_called()


def test_recusa_comando_multilinha_antes_de_conectar(monkeypatch: pytest.MonkeyPatch) -> None:
    """'display\\nreboot' casa com ^display\\b (\\b entre 'y' e '\\n'); o netmiko mandaria
    as duas linhas e o equipamento executaria a segunda. A allowlist é a única
    garantia read-only (§19): rejeitar antes de qualquer conexão."""
    handler = MagicMock(return_value=_conexao_fake())
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", handler)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    with pytest.raises(CommandNotAllowed):
        connect_and_run(dev, "u", "p", ["display\nreboot"], SETTINGS)
    handler.assert_not_called()


def test_fingerprint_ausente_impede_conexao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: _conexao_fake(),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", None
    with pytest.raises(HostKeyMismatch):
        connect_and_run(dev, "u", "p", ["display version"], SETTINGS)


def test_fingerprint_divergente_impede_conexao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: _conexao_fake(),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", "sha256:outra=="
    with pytest.raises(HostKeyMismatch):
        connect_and_run(dev, "u", "p", ["display version"], SETTINGS)


def test_fingerprint_ilegivel_impede_conexao(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _conexao_fake()
    conn.remote_conn.transport.get_remote_server_key.side_effect = Exception("falha ao ler host key")
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", lambda **kwargs: conn)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    with pytest.raises(HostKeyMismatch):
        connect_and_run(dev, "u", "p", ["display version"], SETTINGS)
    conn.disconnect.assert_called_once_with()


def test_conecta_e_roda_com_host_key_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _conexao_fake()
    conn.send_command.return_value = "saida bruta"
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", lambda **kwargs: conn)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    saidas = connect_and_run(dev, "u", "p", ["display version"], SETTINGS)
    assert saidas == {"display version": "saida bruta"}
    conn.send_command.assert_called_once_with("display version", read_timeout=SETTINGS.read_timeout)


def test_usa_porta_ssh_do_device(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs_vistos: dict = {}
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: kwargs_vistos.update(kwargs) or _conexao_fake(),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    dev.ssh_port = 61341
    connect_and_run(dev, "u", "p", ["display version"], SETTINGS)
    assert kwargs_vistos["port"] == 61341


def test_porta_default_22_quando_device_sem_ssh_port(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs_vistos: dict = {}
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: kwargs_vistos.update(kwargs) or _conexao_fake(),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    dev.ssh_port = None
    connect_and_run(dev, "u", "p", ["display version"], SETTINGS)
    assert kwargs_vistos["port"] == 22


def test_apply_recusa_save_e_multilinha_antes_de_conectar(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = MagicMock(return_value=_conexao_fake())
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", handler)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    with pytest.raises(ConfigNotAllowed):
        connect_and_apply(dev, "u", "p", ["save"], SETTINGS)
    with pytest.raises(ConfigNotAllowed):
        connect_and_apply(dev, "u", "p", ["peer 10.0.0.2 enable\nreboot"], SETTINGS)
    handler.assert_not_called()


def test_apply_aceita_comandos_do_plano(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _conexao_fake()
    conn.send_config_set.return_value = "config aplicado"
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", lambda **kwargs: conn)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    saida = connect_and_apply(
        dev, "u", "p",
        ["bgp 65000", "peer 10.0.0.2 as-number 64500", "peer 10.0.0.2 shutdown"],
        SETTINGS,
    )
    assert saida == {"config": "config aplicado"}
    conn.send_config_set.assert_called_once_with(
        ["bgp 65000", "peer 10.0.0.2 as-number 64500", "peer 10.0.0.2 shutdown"],
        read_timeout=SETTINGS.read_timeout,
    )


def test_apply_falha_de_conexao_vira_connection_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: (_ for _ in ()).throw(OSError("ssh para baixo")),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    with pytest.raises(ConnectionFailed):
        connect_and_apply(dev, "u", "p", ["bgp 65000"], SETTINGS)
