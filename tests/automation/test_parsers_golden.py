from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.registry import parse_template

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_version.txt")
FIXTURES = Path("tests/fixtures/huawei_vrp")


def test_parse_version_contra_captura_real() -> None:
    saida = FIXTURE.read_text(encoding="utf-8")
    linhas = parse_template("version", saida)
    assert len(linhas) == 1
    assert linhas[0]["version"]  # versão VRP identificada
    assert linhas[0]["uptime"]


def test_parse_interface_brief_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_interface_brief.txt").read_text(encoding="utf-8")
    linhas = parse_template("int_brief", saida)
    assert len(linhas) == 30
    assert linhas[0] == {"nome": "100GE0/1/53(100M)", "phy": "up", "protocolo": "down"}
    por_nome = {linha["nome"]: linha for linha in linhas}
    assert por_nome["Eth-Trunk127"]["phy"] == "up"
    assert por_nome["Eth-Trunk127"]["protocolo"] == "down"
    assert por_nome["40GE0/1/48"] == {"nome": "40GE0/1/48", "phy": "up", "protocolo": "up"}
    assert por_nome["Eth-Trunk127.582"]["phy"] == "*down"
    assert por_nome["LoopBack0"]["protocolo"] == "up(s)"
    assert por_nome["Nve1"]["phy"] == "up"
    assert "GigabitEthernet0/1/0.1003(10G)" in por_nome


def test_parse_interface_brief_standby_derivado() -> None:
    # Derivado (sintético, spec §10): variante ^down (standby) ausente da captura real.
    saida = (
        "Interface                   PHY   Protocol  InUti OutUti   inErrors  outErrors\n"
        "Eth-Trunk127.900            ^down down         0%     0%          0          0\n"
    )
    assert parse_template("int_brief", saida) == [
        {"nome": "Eth-Trunk127.900", "phy": "^down", "protocolo": "down"},
    ]

def test_parse_ip_interface_brief_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_ip_interface_brief.txt").read_text(encoding="utf-8")
    linhas = parse_template("ip_int_brief", saida)
    assert len(linhas) == 19
    por_nome = {linha["nome"]: linha for linha in linhas}
    assert por_nome["Eth-Trunk127.4024"] == {
        "nome": "Eth-Trunk127.4024", "endereco": "100.110.0.73/30",
        "phy": "up", "protocolo": "up", "vpn": "--",
    }
    assert por_nome["LoopBack0"]["endereco"] == "203.0.113.1/32"
    assert por_nome["GigabitEthernet0/0/0"]["vpn"] == "l3vpn"
    assert por_nome["GigabitEthernet0/0/0"]["endereco"] == "192.168.0.1/24"
    assert por_nome["Eth-Trunk127.582"]["phy"] == "*down"
    assert por_nome["100GE0/1/53(100M)"]["endereco"] == "unassigned"
    assert por_nome["Eth-Trunk127.1500"]["endereco"] == "198.51.100.17/31"
