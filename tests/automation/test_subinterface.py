"""O bloco da subinterface contra a configuração do equipamento (§6).

A pergunta é a mesma no plano e na execução: duas cópias dela divergiriam, e o
plano pularia um bloco que a execução mandaria aplicar — ou o contrário.
"""
from gerenet.automation import subinterface

# A forma curta que o render emite, e a forma longa que o VRP ecoa (§2).
_CURTA = "qos car cir 1024000 inbound"
_LONGA = "qos car cir 1024000 cbs 18700000 green pass red discard inbound"

_CONFIG = """#
interface Eth-Trunk127.626
 vlan-type dot1q 626
 description CIRC-626 NETMAC [1G]
 ip address 100.110.0.13 255.255.255.252
 statistic enable
 qos car cir 1024000 cbs 18700000 green pass red discard inbound
 qos car cir 1024000 cbs 18700000 green pass red discard outbound
#
"""


def test_o_car_completo_do_vrp_e_a_mesma_linha_da_forma_curta() -> None:
    assert subinterface.equivalencia_vrp(_LONGA) == _CURTA
    assert subinterface.equivalencia_vrp(_CURTA) == _CURTA


def test_outra_taxa_nao_e_a_mesma_linha() -> None:
    assert subinterface.equivalencia_vrp(
        "qos car cir 500000 cbs 18700000 green pass red discard inbound"
    ) == "qos car cir 500000 inbound"


def test_as_duas_formas_da_vlan_e_do_ipv6_continuam_equivalentes() -> None:
    assert subinterface.equivalencia_vrp("vlan-type dot1q 1001") == "vlan-type dot1q vid 1001"
    assert subinterface.equivalencia_vrp("ipv6 address 2804:194C::1 126") == "ipv6 address 2804:194C::1/126"


def test_linhas_da_interface_so_pega_o_bloco_e_na_forma_do_render() -> None:
    linhas = subinterface.linhas_da_interface(_CONFIG, "Eth-Trunk127.626")
    assert "description CIRC-626 NETMAC [1G]" in linhas
    assert "vlan-type dot1q vid 626" in linhas
    assert _CURTA in linhas
    assert "qos car cir 1024000 outbound" in linhas
    assert "interface Eth-Trunk127.626" not in linhas  # cabeçalho abre o contexto


def test_linhas_da_interface_nao_vaza_para_o_bloco_vizinho() -> None:
    texto = _CONFIG + "interface Eth-Trunk127.627\n description OUTRO\n"
    assert "description OUTRO" not in subinterface.linhas_da_interface(texto, "Eth-Trunk127.626")


def test_conteudo_conforme_aceita_o_bloco_sem_descricao_e_sem_qos() -> None:
    """Bloco sem as duas linhas não tem o que conferir: conforme. É o caso dos
    blocos escritos à mão nos testes e dos circuitos de antes desta frente —
    marcá-los inconformes faria todo plano congelado reaplicar o parque."""
    assert subinterface.conteudo_conforme(
        ["interface GE1/0/0.2", "vlan-type dot1q vid 2", "ip address 10.0.0.0 255.255.255.254"],
        set(),
    )


def test_conteudo_conforme_recusa_o_bloco_com_descricao_ausente() -> None:
    comandos = ["interface GE1/0/0.2", "description CIRC-2 ACME [1G]", "statistic enable"]
    linhas = subinterface.linhas_da_interface(_CONFIG, "Eth-Trunk127.626")
    assert not subinterface.conteudo_conforme(comandos, linhas)
    assert subinterface.conteudo_conforme(
        comandos, linhas | {"description CIRC-2 ACME [1G]"}
    )


def test_conteudo_conforme_recusa_o_qos_ausente() -> None:
    comandos = ["interface GE1/0/0.2", "statistic enable", _CURTA, "qos car cir 1024000 outbound"]
    linhas = {"description CIRC-2 ACME [1G]"}
    assert not subinterface.conteudo_conforme(comandos, linhas)


def test_conteudo_conforme_confere_a_taxa_e_nao_so_a_presenca() -> None:
    """Taxa diferente é divergência: o bloco entra no plano para convergir."""
    comandos = ["interface GE1/0/0.2", "qos car cir 500000 inbound"]
    assert not subinterface.conteudo_conforme(comandos, {_CURTA})
