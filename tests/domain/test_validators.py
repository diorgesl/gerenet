import pytest

from gerenet.domain.services.errors import ValidationError
from gerenet.domain.validators import (
    asn_valido,
    cidr_valido,
    email_valido,
    endereco_canonico,
    validar_vid,
)


def test_asn_valido_aceita_faixa_publica() -> None:
    assert asn_valido(64512)          # depois do bloco reservado de documentação 64496-64511
    assert asn_valido(132000)
    assert asn_valido(4294967295)     # 32 bits (0xFFFFFFFF; reservado é até 4294967294)


def test_asn_valido_rejeita_reservados() -> None:
    # §14.1/spec: 0, 23456, 64496-64511, 65535-65551, 4200000000-4294967294
    for invalido in (0, 23456, 64496, 64511, 65535, 65536, 65551, 4200000000, 4294967294):
        assert not asn_valido(invalido)


def test_asn_fora_de_32_bits_invalido() -> None:
    assert not asn_valido(-1)
    assert not asn_valido(4294967296)


def test_cidr_valido_aceita_network_alinhada() -> None:
    rede = cidr_valido("100.64.0.0/31")
    assert str(rede.network_address) == "100.64.0.0"
    assert cidr_valido("2804:194C:1000::/48", familia="ipv6")


def test_cidr_desalinhado_ou_nao_ip_rejeitado() -> None:
    with pytest.raises(ValidationError, match="alinhad"):
        cidr_valido("100.64.0.1/31")
    with pytest.raises(ValidationError, match="CIDR inválido"):
        cidr_valido("x.y.z.w/24")
    with pytest.raises(ValidationError, match="não é um prefixo IPv6"):
        cidr_valido("100.64.0.0/31", familia="ipv6")


def test_validar_vid_intervalo() -> None:
    validar_vid(2)
    validar_vid(4094)
    for vid in (0, 1, 4095):
        with pytest.raises(ValidationError):
            validar_vid(vid)


def test_endereco_canonico() -> None:
    """A forma canônica é a do `ipaddress`: o equipamento escreve
    `2804:194C:...` e o cadastro à mão escreve minúsculo, e a identidade do peer
    não pode depender disso."""
    assert endereco_canonico("2804:194C:1000::1100:73:2") == "2804:194c:1000::1100:73:2"
    assert endereco_canonico("2001:0DB8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"
    assert endereco_canonico("100.64.10.1") == "100.64.10.1"


def test_endereco_canonico_devolve_o_texto_quando_nao_e_endereco() -> None:
    # `010.064.010.001` entra na lista porque o `ipaddress` recusa zero à
    # esquerda: não é endereço para ele, e o texto volta como veio.
    for texto in ("", "x.y.z.w", "2804:194C::zz", "10.0.0.1/31", "010.064.010.001"):
        assert endereco_canonico(texto) == texto


def test_email_valido() -> None:
    assert email_valido("noc@provedor.com.br")
    assert not email_valido("sem-arroba")
    assert not email_valido("com espaco@x.com")
    assert not email_valido("a@b")
