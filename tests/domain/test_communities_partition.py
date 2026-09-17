"""A partição do plano (spec §5): faixas, exceções e a conferência de uma linha."""
import pytest

from gerenet.domain.communities_partition import (
    CODIGOS_CONHECIDOS,
    FAIXAS,
    conferir_linha,
    conferir_valor,
    familia_do_digito,
)


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (3001, "v4"), (3101, "v6"), (4001, "v4"), (4101, "v6"),
        (7001, "v4"), (7103, "v6"), (5001, "v4"),
        (1010, None),   # família-agnóstico: a família viaja na large-community
        (992, "v4"), (993, "v6"),   # a família mora no último dígito
        (666, None), (11, None), (90, None), (91, None),
        (3301, None),   # segundo dígito que não é 0 nem 1: fora do padrão
    ],
)
def test_familia_do_digito(valor: int, esperado: str | None) -> None:
    assert familia_do_digito(valor) == esperado


def test_valor_conforme_e_o_que_a_faixa_e_a_familia_aceitam() -> None:
    assert conferir_valor("cliente", 3001, "v4") is None
    assert conferir_valor("transito", 1010, "v6") is None      # agnóstico nas duas colunas
    assert conferir_valor("especial", 993, "v6") is None
    assert conferir_valor("tamanho", 7003, "v4") is None


def test_valor_recusado_por_faixa_e_por_familia() -> None:
    assert conferir_valor("cliente", 4001, "v4") == "fora_da_faixa"
    assert conferir_valor("cliente", 3001, "v6") == "familia_incoerente"
    assert conferir_valor("especial", 992, "v6") == "familia_incoerente"
    assert conferir_valor(None, 3001, "v4") == "sem_banda"
    assert conferir_valor("especial", 3001, "v4") == "fora_da_faixa"


def test_linha_de_instrucao_nao_tem_valor_de_dois_bytes() -> None:
    assert conferir_linha(banda="instrucao", valor_v4=None, valor_v6=None, codigo=666) == ()
    assert conferir_linha(banda="instrucao", valor_v4=None, valor_v6=None, codigo=None) == (
        "instrucao_sem_codigo",
    )
    assert conferir_linha(banda="instrucao", valor_v4=3001, valor_v6=None, codigo=666) == (
        "instrucao_com_valor",
    )


def test_nome_sem_valor_nenhum_nao_e_problema() -> None:
    # `blackhole`, `no-export` e `no-advertise` são semeados sem valor (§4.1).
    assert conferir_linha(banda=None, valor_v4=None, valor_v6=None, codigo=None) == ()


def test_linha_de_classe_relata_o_problema_com_a_familia() -> None:
    assert conferir_linha(banda="cliente", valor_v4=3001, valor_v6=3101, codigo=None) == ()
    problemas = conferir_linha(banda="cliente", valor_v4=3001, valor_v6=3001, codigo=None)
    assert problemas == ("familia_incoerente:v6",)
    assert conferir_linha(banda="tamanho", valor_v4=7103, valor_v6=None, codigo=None) == (
        "familia_incoerente:v4",
    )


def test_as_faixas_da_spec_e_os_codigos_conhecidos() -> None:
    assert FAIXAS["local"] == (1, 99)
    assert FAIXAS["especial"] == (900, 999)
    assert FAIXAS["tamanho"] == (7000, 7999)
    # §6.2 — os códigos de instrução que o plano conhece.
    assert CODIGOS_CONHECIDOS == (1, 2, 3, 4, 6, 100, 666, 6662)
