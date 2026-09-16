"""O bloco da subinterface contra a configuração do equipamento (design §6).

O plano (`changes._ja_existe`) e a execução (`runner._estado_do_bloco`) fazem a
MESMA pergunta — "este bloco já está no equipamento?" — e por isso ela mora
aqui, uma vez só. Duas cópias divergiriam, e a divergência é silenciosa: o
plano pularia um bloco que a execução mandaria aplicar, ou o contrário, e o
operador veria "nada a aplicar" numa mudança que o equipamento não tem.
"""

# As linhas do bloco que a identidade por nome + endereços não cobre. O
# `vlan-type`, os endereços e o `statistic enable` já são cobertos por ela; o
# que falta é a `description` e o QoS (§6).
LINHAS_DE_CONTEUDO = ("description ", "qos car ")


def equivalencia_vrp(texto: str) -> str:
    """Duas linhas que o VRP escreve de duas formas, na forma do render.

    `vlan-type dot1q 1001` e `vlan-type dot1q vid 1001` são a mesma linha, e o
    mesmo vale para `ipv6 address <endereço> 126` e `<endereço>/126`. O parser
    lê as duas formas e o render escreve a segunda, então sem a equivalência
    toda proposta com VLAN e IPv6 nasce com dois falsos `sobrando` e dois falsos
    `faltando`. São a mesma linha escrita de dois jeitos, não dois estados: por
    isso é equivalência, e não normalização de conveniência.

    O `qos car` entrou pela mesma razão, e é o caso mais extremo dos três: o
    render emite `qos car cir 1024000 inbound` e o VRP grava
    `qos car cir 1024000 cbs 18700000 green pass red discard inbound` (§2). Sem
    a dobra, toda subinterface com QoS divergiria para sempre.
    """
    partes = texto.split()
    if len(partes) == 3 and partes[:2] == ["vlan-type", "dot1q"] and partes[2].isdigit():
        return f"vlan-type dot1q vid {partes[2]}"
    if len(partes) == 4 and partes[:2] == ["ipv6", "address"] and partes[3].isdigit():
        return f"ipv6 address {partes[2]}/{partes[3]}"
    if len(partes) >= 5 and partes[:3] == ["qos", "car", "cir"] and partes[-1] in ("inbound", "outbound"):
        # O `cir` está na quarta posição nas duas formas; o `cbs` e as ações
        # caem, e a direção fica porque é ela que separa uma linha da outra.
        return f"qos car cir {partes[3]} {partes[-1]}"
    return texto


def linhas_da_interface(texto: str, nome: str) -> set[str]:
    """Linhas da configuração dentro do bloco `interface <nome>`.

    O cabeçalho fica de fora: ele abre o contexto, não é linha dele. Quem
    compara o nome é a conferência, e por fora — ela põe `interface <nome>` nos
    dois lados (`conferir_fidelidade`), porque o `<trunk>.<vid>` do render
    contra o nome do bloco lido é a única linha que denuncia um trunk errado.

    O contexto é a INDENTAÇÃO (`display current-configuration` escreve os
    sub-comandos com um espaço e os blocos na coluna 0), e não a proximidade
    das linhas: sem ela, um bloco vizinho entraria na conta.

    Comentário (`#`, com ou sem texto) também fica de fora, e antes da regra de
    contexto: o `_normaliza_linhas` já descarta os dois do lado do render, e um
    comentário com texto na coluna 0 zerava o `dentro` aqui — as linhas de
    endereço que vinham depois ficavam de fora da comparação e o render as
    acusava como sobra.
    """
    linhas: set[str] = set()
    dentro = False
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if not bruta[:1].isspace():
            dentro = linha == f"interface {nome}"
            continue
        if dentro:
            linhas.add(equivalencia_vrp(linha))
    return linhas


def conteudo_conforme(comandos: list[str], linhas: set[str]) -> bool:
    """As linhas de conteúdo do bloco estão no que a configuração tem (§6).

    Só `description` e `qos car` entram na conta (`LINHAS_DE_CONTEUDO`). Um
    bloco sem nenhuma delas é conforme: não há o que conferir.

    A comparação é linha a linha e na forma do render, pela `equivalencia_vrp`
    — é ela que faz o `qos car cir 1024000 inbound` do bloco casar com o
    `qos car cir 1024000 cbs 18700000 green pass red discard inbound` do
    equipamento. O espaço interno é normalizado pela mesma regra do
    `_normaliza_linhas`, porque a coluna que separa os tokens não é informação.
    """
    extras = [
        c for c in (" ".join(c.split()) for c in comandos) if c.startswith(LINHAS_DE_CONTEUDO)
    ]
    # A equivalência vale para os DOIS lados: os chamadores de hoje já mandam o
    # conjunto dobrado (`linhas_da_interface`), mas quem mandar a linha crua
    # receberia um falso "não conforme" e reaplicaria o que já está certo.
    dobradas = {equivalencia_vrp(" ".join(linha.split())) for linha in linhas}
    return all(equivalencia_vrp(c) in dobradas for c in extras)
