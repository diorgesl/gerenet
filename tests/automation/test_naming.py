"""Golden do derivador de nomes §25.4/§8 — nomes ≤ 63 chars, maiúsculas, base = ASN do par."""
import pytest

from gerenet.automation import naming
from gerenet.automation.naming import (
    as_path_own,
    pfx_in,
    pfx_produto,
    rp_export,
    rp_import,
    subinterface,
)
from gerenet.domain.services.errors import ValidationError


def test_rp_import_export_pfx_por_afi() -> None:
    assert rp_import(64500, "ipv4") == "RP-64500-IMPORT-V4"
    assert rp_import(64500, "ipv6") == "RP-64500-IMPORT-V6"
    assert rp_export(64500, "ipv4") == "RP-64500-EXPORT-V4"
    assert rp_export(64500, "ipv6") == "RP-64500-EXPORT-V6"
    assert pfx_in(64500, "ipv4") == "IP-PFX-64500-IN-V4"
    assert pfx_in(64500, "ipv6") == "IP-PFX-64500-IN-V6"


def test_pfx_produto_e_subinterface() -> None:
    assert pfx_produto("default", "ipv4") == "IP-PFX-DEFAULT-V4"
    assert pfx_produto("cdn", "ipv6") == "IP-PFX-CDN-V6"
    assert subinterface("Eth-Trunk127", 4024) == "Eth-Trunk127.4024"
    assert subinterface("GE0/0/1", 100) == "GE0/0/1.100"


def test_as_path_own_nome() -> None:
    # §4.1/item 1 da revisão: as-path-filter de rotas próprias (AS-PATH-<ASN>-OWN)
    assert as_path_own(65001) == "AS-PATH-65001-OWN"
    assert len(as_path_own(4294967295)) <= 63
    with pytest.raises(ValidationError, match="ASN"):
        as_path_own(0)


def test_asn_sem_padding_e_limites_de_tamanho() -> None:
    # §25.4: decimal sem padding; 32 bits sem sinal; nenhum nome passa de 63 chars.
    assert rp_import(1, "ipv4") == "RP-1-IMPORT-V4"
    assert rp_import(4294967295, "ipv4") == "RP-4294967295-IMPORT-V4"
    for nome in (
        rp_import(4294967295, "ipv6"),
        rp_export(4294967295, "ipv6"),
        pfx_in(4294967295, "ipv6"),
    ):
        assert len(nome) <= 63


@pytest.mark.parametrize("asn", [0, -1, 4294967296])
def test_asn_invalido_rejeitado(asn: int) -> None:
    with pytest.raises(ValidationError, match="ASN"):
        rp_import(asn, "ipv4")


@pytest.mark.parametrize("afi", ["foo", "ipv3", ""])
def test_afi_invalida_rejeitada(afi: str) -> None:
    with pytest.raises(ValidationError, match="Família inválida"):
        rp_import(64500, afi)


def test_descricao_subinterface_com_velocidade_em_g() -> None:
    assert naming.descricao_subinterface("CIRC-626", "NETMAC", 1024) == "CIRC-626 NETMAC [1G]"


def test_descricao_subinterface_com_velocidade_em_m() -> None:
    assert naming.descricao_subinterface("CIRC-500", "Acme Telecom", 100) == "CIRC-500 ACME TELECOM [100M]"


def test_descricao_subinterface_sem_velocidade_nao_emite_colchetes() -> None:
    assert naming.descricao_subinterface("CIRC-500", "ACME", None) == "CIRC-500 ACME"


def test_descricao_subinterface_nao_multiplo_de_1024_fica_em_m() -> None:
    """3000 Mbps são 2,93 G: arredondar para `3G` mentiria a taxa no rótulo."""
    assert naming.descricao_subinterface("CIRC-7", "ACME", 3000) == "CIRC-7 ACME [3000M]"


def test_descricao_subinterface_dobra_acento_e_sobe_caixa() -> None:
    assert naming.descricao_subinterface("CIRC-1", "Ação Comunicações", 2048) == "CIRC-1 ACAO COMUNICACOES [2G]"


def test_descricao_subinterface_corta_o_nome_no_orcamento() -> None:
    nome = "A" * 200
    linha = naming.descricao_subinterface("CIRC-1", nome, 1024)
    assert linha is not None
    assert len(linha) == naming.LIMITE_DESCRICAO
    assert linha.endswith(" [1G]")
    assert linha.startswith("CIRC-1 A")


def test_descricao_subinterface_sem_espaco_para_o_nome_perde_o_nome() -> None:
    """O teto do código (64) nunca chega aqui na prática — 80 - 64 - 8 - 1 = 7 —
    mas o helper não pode produzir `CIRC-...  [1G]`, com dois espaços."""
    linha = naming.descricao_subinterface("C" * 80, "ACME", 99999)
    assert linha == "C" * 80 + " [99999M]"


def test_descricao_subinterface_sem_organizacao_nao_e_emitida() -> None:
    """`organization_id` é NOT NULL, então não acontece — mas o template escreve
    a linha sempre que o valor é uma string, e `None` é o freio."""
    assert naming.descricao_subinterface("CIRC-1", None, 1024) is None
    assert naming.descricao_subinterface("CIRC-1", "   ", 1024) is None
