"""A proposta de adoção do plano (spec §9): o que ela monta e o que ela não decide."""
from pathlib import Path

from gerenet.automation.community_plan import afi_da_familia, propor_plano
from gerenet.automation.parsers.huawei_vrp.communities_vrp import parse_communities_vrp

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _leitura(nome: str):
    return parse_communities_vrp((FIXTURES / nome).read_text())


def test_propoe_a_classe_com_o_valor_e_a_banda_da_faixa() -> None:
    proposta = propor_plano([_leitura("comunidades_edge.txt")], asn_principal=61785)
    por_nome = {c.nome: c for c in proposta.plano.classes}
    assert por_nome["com-TRANSITO-FULL"].banda == "transito"
    assert por_nome["com-TRANSITO-FULL"].valor_v4 == 1010
    assert por_nome["com-CLIENTES_PARCEIROS-CDN"].banda == "conjunto"


def test_propoe_o_portao_com_aceitas_e_recusadas() -> None:
    """O `not ... matches-any` é a lista de aceitas e o `or ... matches-any` a de
    recusadas, com padrão recusar (§4.4)."""
    proposta = propor_plano([_leitura("comunidades_edge.txt")], asn_principal=61785)
    portoes = {g.nome: g for g in proposta.plano.portoes}
    assert portoes["RouteExportCheck"].padrao == "recusar"
    assert "com-ONLY-CDN" in portoes["RouteExportCheck"].recusadas
    assert portoes["RouteExportCheck"].afi == "ipv4"
    assert portoes["RouteExportCheckV6"].afi == "ipv6"
    assert portoes["RouteExportCheck-PARCEIROS"].papel == "parceiro"


def test_o_portao_do_cdn_e_o_que_aceita_a_classe_so_cdn() -> None:
    """§7: a diferença entre o portão do CDN e o do upstream é o `65000:991`."""
    proposta = propor_plano([_leitura("comunidades_vs.txt")], asn_principal=61785)
    portoes = {g.nome: g for g in proposta.plano.portoes}
    assert portoes["RouteExportCheck"].papel == "cdn"


def test_poda_a_sessao_parada() -> None:
    """§9.3: só Established vira alvo; o resto sai na lista de parados."""
    proposta = propor_plano(
        [_leitura("comunidades_vs.txt")],
        asn_principal=61785,
        estados_alvo={"IX-CG": "established", "EQUINIX_SP": "parado"},
    )
    nomes = {a.nome for a in proposta.plano.alvos}
    assert nomes == {"IX-CG"}
    assert proposta.parados == ("EQUINIX_SP",)


def test_divergencia_de_codigo_ambiguo() -> None:
    """§6.2: o código `3` é ERTEL na borda e prepend 3 no VS — a adoção não escolhe."""
    proposta = propor_plano(
        [_leitura("comunidades_edge.txt"), _leitura("comunidades_vs.txt")], asn_principal=61785
    )
    ambiguos = [d for d in proposta.divergencias if d.codigo == "codigo_ambiguo"]
    assert [d.valor for d in ambiguos] == ["3"]


def test_divergencia_do_nome_que_discorda_da_faixa() -> None:
    """§14.2: `com-CUSTOMER-CLIENTE-v4` é `65000:7001`, que a faixa chama de tamanho.

    O par v6 (`7101`) diverge pelo mesmo motivo, e sai também: a divergência é do
    nome contra a faixa, e vale para as duas linhas.
    """
    proposta = propor_plano([_leitura("comunidades_vs.txt")], asn_principal=61785)
    discordam = [d for d in proposta.divergencias if d.codigo == "nome_e_faixa_discordam"]
    assert [d.valor for d in discordam] == [
        "com-CUSTOMER-CLIENTE-v4",
        "com-CUSTOMER-CLIENTE-v6",
    ]


def test_divergencia_de_papel_duvidoso() -> None:
    """§6.3: o `MSD-CDN-v4` tem nome de CDN e o ASN de um trânsito."""
    proposta = propor_plano(
        [_leitura("comunidades_edge.txt")],
        asn_principal=61785,
        papeis_da_sot={53062: "transito"},
        estados_alvo={"MSD-CDN-v4": "established"},
    )
    duvidosos = [d for d in proposta.divergencias if d.codigo == "papel_duvidoso"]
    assert [d.valor for d in duvidosos] == ["MSD-CDN-v4"]
    alvo = next(a for a in proposta.plano.alvos if a.nome == "MSD-CDN-v4")
    assert alvo.papel == "transito"  # a SoT vence o nome (Regra 5)


def test_o_portao_vira_pendencia_quando_nao_da_para_decidir() -> None:
    texto = """
xpl route-filter RouteExportCheck
 if not community matches-any {65000:4001} then
  refuse
 endif
 end-filter
"""
    proposta = propor_plano([parse_communities_vrp(texto)], asn_principal=61785)
    portao = proposta.plano.portoes[0]
    assert portao.papel == "upstream"   # sem a classe "só CDN", o palpite é o portão de trânsito
    assert any(a.codigo == "portao_sem_evidencia" for a in proposta.divergencias)


def test_a_familia_do_leitor_vira_o_afi_do_plano() -> None:
    """R21: `v4`/`v6` (a língua do leitor) → `ipv4`/`ipv6` (a do §4.1) num lugar só.

    Sem evidência de família o AFI sai por convenção e é o de v4 — o portão neutro
    da produção, cujo gêmeo v6 carrega a família no próprio nome.
    """
    assert afi_da_familia("v4") == "ipv4"
    assert afi_da_familia("v6") == "ipv6"
    assert afi_da_familia(None) == "ipv4"


def test_o_consenso_de_familia_decide_o_afi_quando_o_nome_e_neutro() -> None:
    """R21: sem família no nome, a unanimidade dos valores decide — a convenção só
    entra quando não há evidência nenhuma."""
    texto = """
xpl route-filter RouteExportCheck
 if not community matches-any {65000:4101} then
  refuse
 endif
 end-filter
"""
    proposta = propor_plano([parse_communities_vrp(texto)], asn_principal=61785)
    assert proposta.plano.portoes[0].afi == "ipv6"


def test_o_afi_do_portao_nao_le_a_forma_colada_que_a_guarda_recusa() -> None:
    """R21: o plano usa a **mesma** cadeia da validação; um `"V6" in nome` aqui leria
    `RouteExportCheckV64` como v6 enquanto o detector guardado não vê família nele —
    plano e validação discordando sobre o mesmo filtro."""
    texto = """
xpl route-filter RouteExportCheckV64
 if not community matches-any {65000:4001} then
  refuse
 endif
 end-filter
"""
    proposta = propor_plano([parse_communities_vrp(texto)], asn_principal=61785)
    assert proposta.plano.portoes[0].afi == "ipv4"


def test_o_bloco_de_excecao_nao_vira_parametro_de_alvo() -> None:
    """R22: o bloco não diz a que alvo pertence, então `parametros` sai vazio.

    Pendurado em todo alvo, o `100.64.0.0 10 le 24` do GGC entraria no export do
    `IX-CG` e no do `EQUINIX_SP` — e o template por alvo emitiria bloco alheio.
    """
    proposta = propor_plano(
        [_leitura("comunidades_vs.txt")],
        asn_principal=61785,
        estados_alvo={"IX-CG": "established", "EQUINIX_SP": "established"},
    )
    assert {a.nome for a in proposta.plano.alvos} == {"IX-CG", "EQUINIX_SP"}
    assert all(a.parametros == {} for a in proposta.plano.alvos)


def test_o_bloco_sem_alvo_sai_como_achado() -> None:
    """R22: a evidência que não dá para associar vira achado com filtro, condição e
    linha, e não se perde na proposta."""
    proposta = propor_plano([_leitura("comunidades_vs.txt")], asn_principal=61785)
    achados = [d for d in proposta.divergencias if d.codigo == "excecao_sem_alvo"]
    assert len(achados) == 1
    achado = achados[0]
    assert achado.filtro == "XPL-GGC-V4-EXPORT"
    assert achado.valor == "if ip route-destination in {100.64.0.0 10 le 24} then"
    assert achado.severidade == "atencao"
    assert "15169:12000" in achado.descricao


def test_o_achado_da_excecao_e_um_por_bloco() -> None:
    """R22: a dedup é por (filtro, condição). Dois alvos e duas linhas do mesmo
    bloco dão **um** achado — a multiplicação N×M só mudaria de lugar."""
    texto = """
xpl route-filter XPL-GGC-V4-EXPORT
 if ip route-destination in {100.64.0.0 10 le 24} then
  apply community {15169:12000} additive
  apply community {15169:12001} additive
 endif
 end-filter
bgp 61785
 peer GGC as-number 53062
 peer NFLX as-number 2906
"""
    leitura = parse_communities_vrp(texto)
    proposta = propor_plano(
        [leitura, leitura],
        asn_principal=61785,
        estados_alvo={"GGC": "established", "NFLX": "established"},
    )
    assert {a.nome for a in proposta.plano.alvos} == {"GGC", "NFLX"}
    achados = [d for d in proposta.divergencias if d.codigo == "excecao_sem_alvo"]
    assert len(achados) == 1
    assert "15169:12000" in achados[0].descricao
    assert "15169:12001" in achados[0].descricao
