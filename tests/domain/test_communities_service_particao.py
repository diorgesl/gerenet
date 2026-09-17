"""A guarda de família do catálogo (spec F1, Regra 2 do plano)."""
import pytest

from gerenet.domain.schemas import CommunityCreate, CommunityUpdate
from gerenet.domain.services.communities import create_community, update_community
from gerenet.domain.services.errors import ValidationError


def test_criar_recusa_valor_na_familia_errada(session) -> None:
    with pytest.raises(ValidationError) as erro:
        create_community(
            session,
            CommunityCreate(
                name="com-TESTE-v6", tipo="tag_produto", banda="cliente", valor_v6=3001
            ),
            actor="teste",
        )
    assert "família" in str(erro.value).lower() or "familia" in str(erro.value).lower()


def test_criar_aceita_codigo_fora_do_vocabulario(session) -> None:
    # §14.4: `61785:53062` é exceção legítima e precisa entrar no plano. O caso é
    # `codigo_sem_instrucao` (aviso da partição), não valor fora de faixa.
    com = create_community(
        session,
        CommunityCreate(name="com-ALT", tipo="tag_produto", banda="transito", codigo=53062),
        actor="teste",
    )
    assert com.banda == "transito"
    assert com.codigo == 53062


def test_update_recusa_valor_na_familia_errada(session) -> None:
    com = create_community(
        session, CommunityCreate(name="com-TROCA-v4", tipo="tag_produto", banda="especial", valor_v4=992),
        actor="teste",
    )
    with pytest.raises(ValidationError):
        update_community(session, com.id, CommunityUpdate(valor_v6=992), actor="teste")
