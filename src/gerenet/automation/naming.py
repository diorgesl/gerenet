"""Derivador de nomes VRP §25.4 (spec ciclo B, §5.1).

Nomes ≤ 63 chars, maiúsculas, separador '-', base = ASN do par em decimal
sem padding. Ex.: rp_import(64500, "ipv4") -> "RP-64500-IMPORT-V4".
Prefix-list por produto (IP-PFX-DEFAULT-V4 etc.) usada em T4/T5.
"""
import re
import unicodedata

from gerenet.domain.services.errors import ValidationError

_AFIS = {"ipv4": "V4", "ipv6": "V6"}


def _asn_valido(asn: int) -> str:
    if not 1 <= asn <= 4294967295:
        raise ValidationError(f"ASN inválido para nome VRP: {asn}.")
    return str(asn)


def _afi_valida(afi: str) -> str:
    if afi not in _AFIS:
        raise ValidationError(f"Família inválida: {afi} (esperado ipv4 ou ipv6).")
    return _AFIS[afi]


def rp_import(asn: int, afi: str) -> str:
    """Route-policy de importação: RP-<ASN>-IMPORT-<AFI>."""
    return f"RP-{_asn_valido(asn)}-IMPORT-{_afi_valida(afi)}"


def rp_export(asn: int, afi: str) -> str:
    """Route-policy de exportação: RP-<ASN>-EXPORT-<AFI>."""
    return f"RP-{_asn_valido(asn)}-EXPORT-{_afi_valida(afi)}"


def pfx_in(asn: int, afi: str) -> str:
    """Prefix-list de entrada (autorizações): IP-PFX-<ASN>-IN-<AFI>."""
    return f"IP-PFX-{_asn_valido(asn)}-IN-{_afi_valida(afi)}"


def pfx_produto(produto: str, afi: str) -> str:
    """Prefix-list de produto de exportação: IP-PFX-<PRODUTO>-<AFI>.

    Espaços e underscores do nome lógico viram '-' (separador normalizado §8;
    ex.: pfx_produto("default_internas", "ipv4") -> "IP-PFX-DEFAULT-INTERNAS-V4").
    """
    base = produto.upper().replace(" ", "-").replace("_", "-")
    if len(base) > 20:  # folga para o nome completo ficar ≤ 63
        raise ValidationError(f"Produto longo demais para nome VRP: {produto}.")
    return f"IP-PFX-{base}-{_afi_valida(afi)}"


def as_path_own(asn: int) -> str:
    """As-path-filter de rotas próprias (import up-full): AS-PATH-<ASN>-OWN.

    O nome deriva do ASN local do DEVICE (não do par); a regex do filtro é
    _<ASN>_ — ASN próprio em qualquer posição do AS-PATH (design §4.1).
    """
    return f"AS-PATH-{_asn_valido(asn)}-OWN"


def pfx_export(asn: int, afi: str) -> str:
    """Prefix-list de exportação de upstream: IP-PFX-<ASN>-EXPORT-<AFI>.

    O nome deriva do ASN do par (§25.4) — nunca global: a lista de anúncio
    (rotas internas + autorizadas) é própria de cada upstream (design §4.2).
    """
    return f"IP-PFX-{_asn_valido(asn)}-EXPORT-{_afi_valida(afi)}"


def vsi_nome(name_logico: str, vsi_id: int) -> str:
    """Nome VRP do VSI: VSI-<SIGLA>-<ID> (≤63, maiúsculas, separador '-').

    SIGLA = nome lógico sanitizado (não alfanumérico vira '-', caixa alta),
    limitado a 20 chars — o restante do nome não pode tornar o total > 63
    quando somado ao ID. Ex.: vsi_nome("cliente acme", 12) -> "VSI-CLIENTE-ACME-12".
    """
    if not name_logico.strip():
        raise ValidationError("Nome lógico do VSI vazio.")
    sigla = re.sub(r"[^A-Z0-9]+", "-", name_logico.strip().upper()).strip("-")
    if not sigla:
        raise ValidationError(f"Nome lógico do VSI sem letras/dígitos: {name_logico}.")
    if len(sigla) > 20:
        raise ValidationError(f"Nome longo demais para nome VRP: {name_logico} (máx. 20 chars na sigla).")
    return f"VSI-{sigla}-{vsi_id}"


def subinterface(trunk: str, vid: int) -> str:
    """Nome de subinterface dot1q: <trunk>.<vid>."""
    return f"{trunk}.{vid}"


# Orçamento da `description` da subinterface (§4). O limite real desta versão do
# VRP entra no checklist do runbook; se ele for menor que 80, o número desce
# aqui e a função continua correta, porque o corte é derivado dele.
LIMITE_DESCRICAO = 80


def _dobra_ascii(texto: str) -> str:
    """Maiúsculas e sem acento, com os espaços preservados (§4).

    A convenção observada no equipamento é ASCII (§2): um acento que chegasse
    torto viraria divergência permanente contra a coleta, porque a SoT
    intencionaria uma linha que o VRP nunca escreve igual.
    """
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").upper()


def _velocidade_legivel(velocidade_mbps: int) -> str:
    """Múltiplo de 1024 em `G`, o resto em `M` (§4)."""
    if velocidade_mbps % 1024 == 0:
        return f"{velocidade_mbps // 1024}G"
    return f"{velocidade_mbps}M"


def descricao_subinterface(
    code: str, nome_organizacao: str | None, velocidade_mbps: int | None
) -> str | None:
    """A `description` da subinterface: `<CÓDIGO> <NOME DA ORG> [<VELOCIDADE>]` (§4).

    Devolve o texto SEM a palavra-chave `description` — quem a escreve é o
    template. `None` quando não há nome de organização: a linha não é emitida,
    e não emitida é diferente de emitida com o campo vazio.

    Quem cede no orçamento é o nome da organização, cortado seco. Sobrando menos
    de um caractere para ele, a linha sai como `<CÓDIGO> [<VELOCIDADE>]`, sem
    espaço dobrado.
    """
    nome = _dobra_ascii(nome_organizacao or "").strip()
    if not nome:
        return None
    sufixo = f" [{_velocidade_legivel(velocidade_mbps)}]" if velocidade_mbps is not None else ""
    espaco = LIMITE_DESCRICAO - len(code) - len(sufixo) - 1
    if espaco < 1:
        return f"{code}{sufixo}"
    return f"{code} {nome[:espaco]}{sufixo}"
