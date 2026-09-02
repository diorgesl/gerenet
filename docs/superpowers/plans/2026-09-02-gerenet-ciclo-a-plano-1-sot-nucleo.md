# Ciclo A — Plano 1: Núcleo da Source of Truth (sites, organizações, contatos, circuitos) + IPAM + auditoria

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar o núcleo da fonte de verdade de downstreams do gerenet: tabelas/regras de `sites`, `organizations`, `contacts`, `circuits`, `vlans` e `ip_prefixes` (p2p), alocador de enlace IPv4 `/31`|`/30` + IPv6 `/126` derivado (§25.8), reserva de circuito idempotente e auditoria de CRUD imutável com mascaramento — com retrofit dos devices da F1 (`site` string → `site_id` FK, `asn`, auditoria).

**Architecture:** Segue o padrão F1 já existente: modelos SQLAlchemy em `domain/models.py`, serviços com regras de negócio em `domain/services/`, mensagens de erro PT-BR (`GerenetError`/`NotFoundError`/`ConflictError`/nova `ValidationError`), Pydantic `Create`/`Update` em `domain/schemas.py`, migração Alembic aplicada nos dois bancos (`gerenet` e `gerenet_test`), TRUNCATE por teste no `conftest.py`. O alocador IPAM é dividido em funções puras (sufixo IPv6, pontas, blocos) + serviço transacional idempotente. Auditoria nova grava `AuditEvent` com `details={objeto, objeto_id, antes, depois}` e mascara campos sensíveis.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic, PostgreSQL (compose dev), Pydantic v2, pytest com banco real truncado por teste, `uv` para comandos.

**Spec:** [docs/superpowers/specs/2026-09-02-gerenet-ciclo-a-sot-downstreams-design.md](../specs/2026-09-02-gerenet-ciclo-a-sot-downstreams-design.md) — o plano argumenta a partir da spec; o executor lê ambas. O ciclo A foi fatiado em 3 planos: **este** (núcleo + IPAM + auditoria), Plano 2 (sessões BGP, prefixos autorizados, produtos, communities), Plano 3 (API REST nova + CLI nova + endpoints de auditoria). As tabelas BGP **não** entram neste plano — elas nascem no Plano 2 (segunda migration), para cada plano entregar software testável próprio.

## Global Constraints

- Idioma dos artefatos: **PT-BR**; código (identificadores, nomes de tabelas/colunas, tipos de enum) em **inglês** — padrão F1.
- Mensagens de erro de domínio em PT-BR via exceções de `gerenet.domain.services.errors`.
- **Nunca** credencial/segredo em banco, YAML, Git, logs, snapshots ou auditoria — só Vault (padrão F1). Este plano não mexe em segredos (password BGP é do Plano 2).
- Soft-delete via `admin_status` em todas as entidades novas; desativar nunca exclui (§14.1).
- **Antes de ler código-fonte, rodar `graphify query "<assunto>"`** — regra do repositório (vale para subagentes).
- Rodar a suíte com o compose dev de pé (`docker compose up -d`): postgres com os bancos `gerenet` e `gerenet_test` migrados.
- TDD: teste falha → implementação mínima → teste passa → **commit por task** com `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
- Comandos: `uv run pytest` (suíte toda), `uv run pytest <arquivo> -v` (um arquivo), `uv run alembic upgrade head` (dev) e `GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head` (test).
- Cadeia de migrations atual: `4b9aa889400e` (initial) → `a8acda79738d` (ssh_port) → **a nova** (`down_revision="a8acda79738d"`).
- Auditoria de CRUD: helper `domain/audit.py`; tipos de evento `"<objeto>.<acao>"` com ações `create`/`update`/`disable` + `circuit.reserve`; `details = {"objeto", "objeto_id", "antes", "depois"}`; `antes`/`depois` com **apenas** os campos alterados (create: `antes=None`, `depois` = dump completo do schema de entrada; disable: transição booleana). Eventos antigos da F1 (`collect.*`, `hostkey.*`) permanecem como estão.
- Retrofit de devices: `services/devices.py` ganha parâmetro `*, actor` em `create_device`/`disable_device` — **todo** chamador passa `actor="api"|"cli"`.
- Banco dev tem dados reais (NE8000 do lab, snapshots): a migration preserva a coluna `site` (string) migrando para `sites` homônimos — nunca dropar dado.
- `tests/conftest.py` TRUNCATE por teste precisa listar as tabelas novas (senão testes vazam estado entre si).
- Enum `family` e `alloc_status` compartilham nome PG (`"family"`, `"alloc_status"`) — um único `CREATE TYPE` por nome; no autogenerate, o nome sairia com `name='family'`/`name='alloc_status'`.
- Regras de lint implícitas (sem runner): código no estilo do repo (aspas simples, type hints `Mapped[...]`, `Session` tipada).
- Ledger do SDD (execução): `.superpowers/sdd/2026-09-02-gerenet-ciclo-a-plano-1-sot-nucleo/progress.md`.

## Decisões deste plano (rulings sobre a spec — registrar no ledger do SDD)

1. **`UNIQUE(site_id, network)` em `ip_prefixes`** além da regra de serviço de sobreposição — rede de segurança contra duplicidade exata concorrente (o overlap lógico segue em serviço, como manda a spec §4).
2. **Contatos têm `admin_status`** (spec corrigida nesta data) — exigido pelo §6 (disable) e §14.1.
3. **`reservar_circuito(session, circuit_id, *, actor)`** sem `origin` (spec corrigida nesta data) — ator = origem (`api`|`cli`), consistente com a auditoria.
4. **`derivar_v6` é função total com guarda**: se os octetos 2–4 concatenados excederem 8 dígitos (ex.: `100.127.255.255` → `127255255`, 9 dígitos, não cabe em 2 hextets), levanta `ValidationError` — na prática o bloco p2p `100.64/10` real não alcança isso (ocorreria só com octeto 2 ≥ 100), mas a função pura não pode produzir endereço inválido silenciosamente.
5. **Auditoria registra antes do commit na mesma transação** da mudança (rollback descarta ambos); create usa `model_dump()` completo do schema como `depois`; `disable` idempotente só audita quando há transição (`antes != depois`).
6. **Status `liberada`** de `vlans`/`ip_prefixes` não é reaproveitado pelo alocador neste ciclo (a liberação explícita é do ciclo C) — o alocador conta como ocupadas apenas linhas `reservada`.
7. **Colisão do sufixo v6 derivado**: a concatenação decimal dos octetos 2–4 **não é injetiva** (ex.: `100.64.1.22` e `100.64.12.2` produzem ambos `"64122"`) — dois enlaces v4 distintos poderiam derivar o mesmo `/126`. A reserva verifica se a rede v6 derivada já existe no site e, em caso positivo, falha com `ConflictError` claro em vez de violar o `UNIQUE` silenciosamente. Custo: só ocorre em sites com centenas de circuitos; a resolução fina (pular para o próximo v4 cujo sufixo esteja livre) fica como dívida anotada para o ciclo C.

---

## Estrutura de arquivos

**Criar:**
- `src/gerenet/domain/validators.py` — validações puras compartilhadas (ASN, CIDR, VID, e-mail)
- `src/gerenet/domain/audit.py` — helper de auditoria com mascaramento
- `src/gerenet/domain/services/ipam.py` — alocador: puras (sufixo/pontas/bloco) + `reservar_circuito` transacional
- `src/gerenet/domain/services/sites.py` — CRUD de sites + `link_device`
- `src/gerenet/domain/services/organizations.py` — CRUD de organizações
- `src/gerenet/domain/services/contacts.py` — CRUD de contatos
- `src/gerenet/domain/services/circuits.py` — CRUD de circuitos (valida vínculo com o site)
- `alembic/versions/<rev>_sot_core.py` — migration (autogenerate revisado + data move de `devices.site`)
- `tests/domain/test_validators.py`, `test_audit.py`, `test_ipam.py`, `test_sites_service.py`, `test_organizations_service.py`, `test_contacts_service.py`, `test_circuits_service.py`, `test_reserva_circuito.py`

**Modificar:**
- `src/gerenet/domain/models.py` — 6 classes novas (`Site`, `Organization`, `Contact`, `Circuit`, `Vlan`, `IpPrefix`) + `Device.site_id`/`Device.asn` (remove `Device.site`)
- `src/gerenet/domain/schemas.py` — `DeviceCreate/Update/Out` com `site_id`/`asn`; schemas `Site*`, `Organization*`, `Contact*`, `Circuit*`
- `src/gerenet/domain/services/errors.py` — adiciona `ValidationError`
- `src/gerenet/domain/services/devices.py` — validação de ASN, parâmetro `actor`, auditoria
- `src/gerenet/api/routers/devices.py` — passa `actor`, audita `criar`/`atualizar`
- `src/gerenet/cli/devices.py` — `--site-id`, `--asn`, passa `actor`
- `src/gerenet/config.py` — settings `p2p_ipv4_block`/`p2p_ipv6_base`
- `tests/conftest.py` — lista do TRUNCATE
- `tests/domain/test_models.py`, `test_devices_service.py`, `tests/api/test_devices_api.py` — ajustes dos retrofits

---

### Task 1: `ValidationError` + validadores compartilhados

**Files:**
- Modify: `src/gerenet/domain/services/errors.py` (arquivo inteiro — hoje tem só `GerenetError`, `NotFoundError`, `ConflictError`)
- Create: `src/gerenet/domain/validators.py`
- Test: `tests/domain/test_validators.py`

**Interfaces:**
- Produces: `gerenet.domain.services.errors.ValidationError(GerenetError)`; `validators.asn_valido(asn: int) -> bool`; `validators.cidr_valido(cidr: str, familia: str | None = None) -> ipaddress.IPv4Network | ipaddress.IPv6Network` (levanta `ValidationError`); `validators.validar_vid(vid: int) -> None`; `validators.email_valido(email: str) -> bool`. Todas as tasks seguintes consomem estas.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/domain/test_validators.py`:

```python
import pytest

from gerenet.domain.services.errors import ValidationError
from gerenet.domain.validators import asn_valido, cidr_valido, email_valido, validar_vid


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


def test_email_valido() -> None:
    assert email_valido("noc@provedor.com.br")
    assert not email_valido("sem-arroba")
    assert not email_valido("com espaco@x.com")
    assert not email_valido("a@b")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_validators.py -v`
Expected: FAIL — `ModuleNotFoundError: gerenet.domain.validators` / `ValidationError` inexistente.

- [ ] **Step 3: Implementar**

Sobrescreva `src/gerenet/domain/services/errors.py`:

```python
class GerenetError(Exception):
    """Erro de domínio do gerenet (mensagens em PT-BR)."""


class NotFoundError(GerenetError):
    """Objeto não encontrado (HTTP 404)."""


class ConflictError(GerenetError):
    """Conflito com o estado atual (HTTP 409)."""


class ValidationError(GerenetError):
    """Dado inválido, sem conflito com o estado (HTTP 400 no Plano 3)."""
```

Crie `src/gerenet/domain/validators.py`:

```python
"""Validações puras compartilhadas pelos serviços (mensagens PT-BR)."""
import ipaddress
import re

from gerenet.domain.services.errors import ValidationError

# Faixas reservadas que nunca podem ser ASN de organização/par (§14.1, spec ciclo A):
# 0, 23456 (AS_TRANS), 64496-64511 e 65536-65551 (documentação RFC 5398),
# 65535 (reservado), 4200000000-4294967294 (documentação 32 bits).
_ASN_RESERVADAS: tuple[tuple[int, int], ...] = (
    (0, 0),
    (23456, 23456),
    (64496, 64511),
    (65535, 65551),
    (4200000000, 4294967294),
)

# Mensagem do ipaddress quando os host bits estão setados ("100.64.0.1/31 has host
# bits set") — estável entre versões; distingue "desalinhado" de "não é CIDR".
_HOST_BITS_SET = re.compile(r"has host bits set")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def asn_valido(asn: int) -> bool:
    """ASN válido de 32 bits e fora das faixas reservadas."""
    if not (1 <= asn <= 4294967295):
        return False
    return not any(inicio <= asn <= fim for inicio, fim in _ASN_RESERVADAS)


def cidr_valido(cidr: str, familia: str | None = None) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Valida um CIDR alinhado ao prefixo (host bits zerados).

    familia: "ipv4" | "ipv6" — quando informada, exige essa versão.
    """
    try:
        rede = ipaddress.ip_network(cidr, strict=True)
    except ValueError as exc:
        if _HOST_BITS_SET.search(str(exc)):
            raise ValidationError(f"CIDR {cidr} não está alinhado ao prefixo.") from exc
        raise ValidationError(f"CIDR inválido: {cidr}.") from exc
    if familia == "ipv4" and rede.version != 4:
        raise ValidationError(f"O CIDR {cidr} não é um prefixo IPv4.")
    if familia == "ipv6" and rede.version != 6:
        raise ValidationError(f"O CIDR {cidr} não é um prefixo IPv6.")
    return rede


def validar_vid(vid: int) -> None:
    """VID de VLAN: 2–4094 (1 é a nativa; 0/4095 reservados)."""
    if not 2 <= vid <= 4094:
        raise ValidationError(f"VID fora do intervalo permitido (2–4094): {vid}.")


def email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.fullmatch(email))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_validators.py -v`
Expected: PASS (8 testes).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/domain/services/errors.py src/gerenet/domain/validators.py tests/domain/test_validators.py
git commit -m "feat: ValidationError e validadores compartilhados (ASN, CIDR, VID, e-mail)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Modelos do núcleo + migração `sot_core` + conftest

**Files:**
- Modify: `src/gerenet/domain/models.py` (Device: `site`→`site_id`+`asn`; classes novas abaixo de `AuditEvent`)
- Create: `alembic/versions/<rev>_sot_core.py` (autogenerate + edição manual)
- Modify: `tests/conftest.py` (lista do TRUNCATE)
- Modify: `tests/domain/test_models.py` (estende com roundtrip do núcleo)

**Interfaces:**
- Produces: classes `Site`, `Organization`, `Contact`, `Circuit`, `Vlan`, `IpPrefix` com as colunas exatas da spec §4 (nomes/Enums abaixo) e enums de módulo: `ORG_KIND=("downstream","parceiro")`, `CONTACT_KIND=("tecnico","noc","admin")`, `CIRCUIT_STACK=("ipv4","ipv6","dual")`, `VLAN_MODE=("unica","separada")`, `VLAN_KIND=("vlan","s_vlan")`, `FAMILY=("ipv4","ipv6")`, `ALLOC_STATUS=("reservada","liberada")`, `PREFIX_KIND=("p2p",)` — com nomes PG `org_kind`, `contact_kind`, `circuit_stack`, `vlan_mode`, `vlan_kind`, `family`, `alloc_status`, `prefix_kind`. `Device`: `site_id: Mapped[int|None]` FK `sites.id` + `site` relationship, `asn: Mapped[int|None]`; coluna string `site` removida. As tasks 3+ consomem estes nomes verbatim.

- [ ] **Step 1: Atualizar `Device` e criar as classes no `models.py`**

Substitua, no `Device`, a coluna:

```python
    site: Mapped[str | None] = mapped_column(String(64))
```

por:

```python
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"))
    asn: Mapped[int | None] = mapped_column(Integer)  # ASN local do roteador (§5)
```

e adicione, na área de relationships do `Device` (ao lado de `snapshots`/`credential_group`):

```python
    site: Mapped["Site | None"] = relationship(back_populates="devices")
```

No topo do arquivo, após `JOB_STATUS`, adicione as tuplas:

```python
ORG_KIND = ("downstream", "parceiro")
CONTACT_KIND = ("tecnico", "noc", "admin")
CIRCUIT_STACK = ("ipv4", "ipv6", "dual")
VLAN_MODE = ("unica", "separada")
VLAN_KIND = ("vlan", "s_vlan")
FAMILY = ("ipv4", "ipv6")
ALLOC_STATUS = ("reservada", "liberada")
PREFIX_KIND = ("p2p",)
```

Ajuste o import do `sqlalchemy` no topo — de `from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, func` para acrescentar `Text, UniqueConstraint` (mantenha os já existentes):

```python
from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
```

No **fim** do arquivo (após `AuditEvent`), adicione as 6 classes — estilo idêntico ao da F1 (colunas `created_at`/`updated_at` com `server_default=func.now()`, `onupdate=func.now()`):

```python
class Site(Base):
    """POP/local. Escopo padrão das regras de unicidade do §14.1."""

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    city: Mapped[str | None] = mapped_column(String(128))
    uf: Mapped[str | None] = mapped_column(String(2))
    p2p_ipv4_block: Mapped[str | None] = mapped_column(String(64))  # default: settings
    p2p_ipv6_base: Mapped[str | None] = mapped_column(String(64))  # default: settings
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    devices: Mapped[list["Device"]] = relationship(back_populates="site")


class Organization(Base):
    """Cliente (downstream) ou parceiro. ASN único mesmo desativado (§14.1)."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(Enum(*ORG_KIND, name="org_kind"), default="downstream", nullable=False)
    asn: Mapped[int | None] = mapped_column(Integer, unique=True)
    irr_as_set: Mapped[str | None] = mapped_column(String(64))
    commercial_status: Mapped[str] = mapped_column(String(16), default="ativo", nullable=False)
    operational_status: Mapped[str] = mapped_column(String(16), default="ativo", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    contacts: Mapped[list["Contact"]] = relationship(back_populates="organization")


class Contact(Base):
    """Contato de uma organização (técnico/NOC/admin)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(
        Enum(*CONTACT_KIND, name="contact_kind"), default="tecnico", nullable=False
    )
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="contacts")


class Circuit(Base):
    """Circuito de acesso de um downstream no POP (acesso do switch até o edge NE8000)."""

    __tablename__ = "circuits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    access_device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    access_port: Mapped[str] = mapped_column(String(64), nullable=False)
    edge_device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    backup_edge_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    stack: Mapped[str] = mapped_column(Enum(*CIRCUIT_STACK, name="circuit_stack"), default="dual", nullable=False)
    vlan_mode: Mapped[str] = mapped_column(Enum(*VLAN_MODE, name="vlan_mode"), default="unica", nullable=False)
    qinq: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vrf: Mapped[str | None] = mapped_column(String(64))  # None = instância pública (§25.3)
    mtu: Mapped[int | None] = mapped_column(Integer)
    bandwidth: Mapped[str | None] = mapped_column(String(32))
    bfd: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    p2p_v4_len: Mapped[int] = mapped_column(Integer, default=31, nullable=False)  # /31 padrão, /30 opção
    description: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship()


class Vlan(Base):
    """VLAN reservada num site para um circuito (kind vlan ou s_vlan no QinQ)."""

    __tablename__ = "vlans"

    __table_args__ = (
        # S-VLAN e VLAN partilham o mesmo espaço de VID no switch (spec)
        UniqueConstraint("site_id", "vid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    vid: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Enum(*VLAN_KIND, name="vlan_kind"), default="vlan", nullable=False)
    family: Mapped[str | None] = mapped_column(Enum(*FAMILY, name="family"))
    circuit_id: Mapped[int | None] = mapped_column(ForeignKey("circuits.id"))
    status: Mapped[str] = mapped_column(
        Enum(*ALLOC_STATUS, name="alloc_status"), default="reservada", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IpPrefix(Base):
    """Enlace p2p reservado num site (v4 /31|/30 e v6 /126 derivado §25.8)."""

    __tablename__ = "ip_prefixes"

    __table_args__ = (
        # Ruling 1: rede de segurança contra duplicidade exata no site
        UniqueConstraint("site_id", "network"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network: Mapped[str] = mapped_column(String(64), nullable=False)  # CIDR canônico alinhado
    kind: Mapped[str] = mapped_column(Enum(*PREFIX_KIND, name="prefix_kind"), default="p2p", nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    circuit_id: Mapped[int | None] = mapped_column(ForeignKey("circuits.id"))
    status: Mapped[str] = mapped_column(
        Enum(*ALLOC_STATUS, name="alloc_status"), default="reservada", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 2: Estender `tests/domain/test_models.py`** — acrescente ao fim do arquivo (o arquivo já importa `Device` e `Session`; adicione `Circuit, Contact, IpPrefix, Organization, Site, Vlan` ao import de `gerenet.domain.models`):

```python
def test_nucleo_so_t_roundtrip(db_session: Session) -> None:
    site = Site(name="pop-spo-01", p2p_ipv4_block="100.64.0.0/24")
    db_session.add(site)
    db_session.flush()

    org = Organization(name="Cliente X", asn=64512)
    db_session.add(org)
    db_session.flush()

    contato = Contact(organization_id=org.id, name="Fulano", email="noc@x.com.br")
    db_session.add(contato)

    dev = Device(name="ne8k-lab", management_address="10.0.0.9", site_id=site.id)
    db_session.add(dev)
    db_session.flush()

    circ = Circuit(
        code="CIRC-0001",
        organization_id=org.id,
        site_id=site.id,
        access_device_id=dev.id,
        access_port="GE0/0/1",
        edge_device_id=dev.id,
    )
    db_session.add(circ)
    db_session.flush()

    vlan = Vlan(site_id=site.id, vid=100, circuit_id=circ.id)
    rede = IpPrefix(site_id=site.id, network="100.64.0.0/31", circuit_id=circ.id)
    db_session.add_all([vlan, rede])
    db_session.commit()

    assert db_session.get(Site, site.id).name == "pop-spo-01"
    assert db_session.get(Organization, org.id).asn == 64512
    assert db_session.get(Circuit, circ.id).vlan_mode == "unica"
    assert db_session.get(Vlan, vlan.id).status == "reservada"
    assert db_session.get(IpPrefix, rede.id).kind == "p2p"
```

- [ ] **Step 3: Gerar a migration e editá-la**

Run: `uv run alembic revision --autogenerate -m "sot_core"`

O arquivo gerado terá (revise cada item):
1. `create_table` para `sites`, `organizations`, `contacts`, `circuits`, `vlans`, `ip_prefixes` — **nesta ordem** (dependências FK); enums inline `sa.Enum(*, name=...)`; `sa.UniqueConstraint("site_id", "vid")` em `vlans` e `sa.UniqueConstraint("site_id", "network")` em `ip_prefixes`.
2. Ops sobre `devices`: `sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), nullable=True)` (ou `create_foreign_key`), `sa.Column("asn", sa.Integer(), nullable=True)` e `op.drop_column("devices", "site")`.

**Edite manualmente** (o autogenerate NÃO garante ordem nem preserva dados):
- `revision` = hash gerado; `down_revision = "a8acda79738d"`. Renomeie o arquivo para `alembic/versions/<hash>_sot_core.py` se o slug vier diferente.
- O `upgrade()` deve (a) criar as 6 tabelas, (b) adicionar `site_id`/`asn` em `devices` — os dois `add_column` **depois** de `create_table("sites")` —, (c) migrar os dados da coluna `site` e só então (d) dropar `devices.site`. Substitua o corpo pelo seguinte (mantendo os `op.create_table(...)` gerados intactos no início):

```python
def upgrade() -> None:
    """Núcleo da SoT: sites/organizações/contatos/circuitos + VLANs/enlaces p2p.

    devices.site (string, F1) vira devices.site_id → sites homônimos criados
    a partir dos valores existentes (dados preservados, §14.1).
    """
    op.create_table("sites", ...)          # mantido do autogenerate
    op.create_table("organizations", ...)  # mantido do autogenerate
    op.create_table("contacts", ...)       # mantido do autogenerate
    op.create_table("circuits", ...)       # mantido do autogenerate
    op.create_table("vlans", ...)          # mantido do autogenerate
    op.create_table("ip_prefixes", ...)    # mantido do autogenerate
    op.add_column("devices", sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), nullable=True))
    op.add_column("devices", sa.Column("asn", sa.Integer(), nullable=True))

    # Data move: cada valor distinto de devices.site vira um site homônimo.
    bind = op.get_bind()
    nomes = bind.execute(
        sa.text("select distinct site from devices where site is not null and site <> ''")
    ).scalars()
    for nome in nomes:
        bind.execute(
            sa.text("insert into sites (name) values (:nome) on conflict do nothing"),
            {"nome": nome},
        )
    bind.execute(
        sa.text(
            "update devices d set site_id = s.id "
            "from sites s where s.name = d.site and d.site is not null and d.site <> ''"
        )
    )
    op.drop_column("devices", "site")


def downgrade() -> None:
    """Restaura a coluna site (string) com o nome do site de cada device."""
    op.add_column("devices", sa.Column("site", sa.String(length=64), nullable=True))
    bind = op.get_bind()
    bind.execute(
        sa.text("update devices d set site = s.name from sites s where s.id = d.site_id")
    )
    op.drop_column("devices", "site_id")
    op.drop_column("devices", "asn")
    op.drop_table("ip_prefixes")
    op.drop_table("vlans")
    op.drop_table("circuits")
    op.drop_table("contacts")
    op.drop_table("organizations")
    op.drop_table("sites")
```

> Se o autogenerate emitiu o `drop_column("devices", "site")` no meio dos `create_table`, mova-o para depois do data move como acima. Se os `add_column` de `devices` vieram antes dos `create_table`, mova-os para depois.
> **Enums compartilhados no upgrade:** `alloc_status` (vlans.status e ip_prefixes.status) e `family` aparecem em mais de uma tabela com o mesmo `name=` (o autogenerate costuma emiti-los inline em cada `create_table`). O `op.create_table` executa com `checkfirst`, então o segundo `CREATE TYPE` é pulado — se, por alguma variação do autogenerate, o upgrade falhar com `type "alloc_status" already exists`, troque a ocorrência duplicada (a de `ip_prefixes.status`) por `sa.Enum(..., name="alloc_status", create_type=False)` e o mesmo para `family` se duplicar.

- [ ] **Step 4: Atualizar a lista do TRUNCATE no conftest e migrar os dois bancos**

Em `tests/conftest.py`, a linha do TRUNCATE passa a listar as tabelas novas na ordem de dependência (filhas primeiro):

```python
            "TRUNCATE audit_events, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups RESTART IDENTITY CASCADE"
```

Run:
```bash
uv run alembic upgrade head
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head
```

Verifique contra o banco dev que o dado do lab foi preservado:
```bash
docker compose exec -T db psql -U gerenet -d gerenet -c "select d.name, d.site_id, s.name as site from devices d left join sites s on s.id = d.site_id where d.name = 'ne8k-lab';"
```
> Se nenhum device tinha `site` preenchido, a linha retorna `site_id` nulo — ok. Se algum tinha, o site homônimo deve existir. Depois valide a reversibilidade no banco de teste:

```bash
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic downgrade -1
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head
```

- [ ] **Step 5: Rodar a suíte e ver passar**

Run: `uv run pytest -v`
Expected: PASS — os 32 testes da F1 (incl. os ajustados de `test_models.py`) + o novo roundtrip. O `test_device_roundtrip` antigo continua igual (não usava `site`).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/models.py tests/domain/test_models.py tests/conftest.py alembic/versions/
git commit -m "feat: modelos do núcleo da SoT (sites/organizações/contatos/circuitos/vlans/p2p) + devices.site_id/asn

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Retrofit dos devices da F1 (schema, CLI, validação de ASN) para `site_id`/`asn`

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`DeviceCreate`, `DeviceUpdate`, `DeviceOut`)
- Modify: `src/gerenet/domain/services/devices.py` (validação de `asn`)
- Modify: `src/gerenet/cli/devices.py` (comando `add`)
- Modify: `tests/domain/test_devices_service.py` (novo teste de ASN)
- Modify: `tests/api/test_devices_api.py` (se necessário, sem `site`)

**Interfaces:**
- Consumes: `validators.asn_valido` (Task 1), modelos com `site_id`/`asn` (Task 2).
- Produces: `DeviceCreate` com `site_id: int | None` e `asn: int | None` (sem campo `site`); `DeviceUpdate` com `site_id`/`asn` opcionais; `DeviceOut` com `site_id: int | None` e `asn: int | None` (sem `site`). CLI `gerenet devices add` com `--site-id` e `--asn`. O serviço `create_device` **não** muda de assinatura nesta task (o `actor` entra na Task 5).

- [ ] **Step 1: Ajustar os schemas** em `src/gerenet/domain/schemas.py`:

Em `DeviceCreate`, troque a linha `site: str | None = None` por:

```python
    site_id: int | None = None
    asn: int | None = Field(default=None, ge=1, le=4294967295)  # reservados barrados no serviço
```

Em `DeviceUpdate`, troque `site: str | None = None` por:

```python
    site_id: int | None = None
    asn: int | None = Field(default=None, ge=1, le=4294967295)
```

> Atenção: em `DeviceUpdate`, omitir o campo = "não mudar"; `null` explícito limpa o valor. Em `DeviceOut`, troque `site: str | None` por:

```python
    site_id: int | None
    asn: int | None
```

- [ ] **Step 2: Validar o ASN no serviço** — em `src/gerenet/domain/services/devices.py`, ajuste os imports e o `create_device`:

```python
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.validators import asn_valido
```

```python
    if data.asn is not None and not asn_valido(data.asn):
        raise ValidationError(f"ASN inválido ou reservado: {data.asn}.")
```

(inserido em `create_device`, antes do `models.Device(**data.model_dump())`).

- [ ] **Step 3: Ajustar o CLI** — em `src/gerenet/cli/devices.py`, no comando `add`, troque o parâmetro `site` (string) por estes dois:

```python
    site_id: int | None = typer.Option(None, "--site-id", help="ID do site/POP."),
    asn: int | None = typer.Option(None, "--asn", min=1, max=4294967295, help="ASN local do roteador."),
```

e no `DeviceCreate(...)` montado dentro do `add`, troque `site=site` por:

```python
                    site_id=site_id,
                    asn=asn,
```

- [ ] **Step 4: Conferir a suíte e os testes tocados**

Run: `uv run pytest tests/domain/test_devices_service.py tests/api/test_devices_api.py tests/domain/test_validators.py -v`
Expected: PASS sem alterações nos testes existentes (nenhum usava `site`). Se algum teste construir `DeviceCreate(site=...)`, troque por `site_id=...` (e ajuste a asserção do `DeviceOut` se checar `site`).

Adicione um caso ao `tests/domain/test_devices_service.py` cobrindo o ASN inválido (o arquivo já importa `create_device` e `DeviceCreate`; acrescente `pytest` e `ValidationError` se não existirem, e `Session` ao import da sqlalchemy se preciso):

```python
def test_asn_reservado_vira_erro_de_validacao(db_session: Session) -> None:
    with pytest.raises(ValidationError, match="reservado"):
        create_device(db_session, DeviceCreate(name="ne8k", management_address="10.0.0.7", asn=23456), actor="cli")
```

> A task 5 ainda não existe quando esta roda: os testes existentes chamam `create_device(db_session, ...)` sem `actor`. Se o `actor` **já estiver** obrigatório no momento em que você implementa (por ter rodado depois da Task 5 num re-run), acrescente `actor="cli"` aqui e nos demais testes tocados — a suíte acusa onde faltar.

- [ ] **Step 5: Rodar a suíte toda**

Run: `uv run pytest -v`
Expected: PASS (33+ testes).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/devices.py src/gerenet/cli/devices.py tests/
git commit -m "feat: devices com site_id e asn (schemas, CLI e validação de ASN)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Helper de auditoria (`domain/audit.py`)

**Files:**
- Create: `src/gerenet/domain/audit.py`
- Test: `tests/domain/test_audit.py`

**Interfaces:**
- Consumes: `models.AuditEvent` (F1 — tipo `type`, `actor`, `details` JSON, sem `updated_at`).
- Produces: `CAMPO_SENSIVEL = ("password", "senha", "secret", "token")`; `mascarar(paineis: Mapping[str, dict | None]) -> dict[str, dict | None]` (exportado para teste); `registrar(session, *, tipo, ator, objeto, objeto_id, antes=None, depois=None) -> None` — grava `AuditEvent(type=tipo, actor=ator, details={"objeto": objeto, "objeto_id": objeto_id, "antes": antes, "depois": depois})` **sem commit** (o chamador commita junto com a mudança — Ruling 5). Campos com chave sensível (substring case-insensitive) são removidos de `antes`/`depois`; quando a chave estava em `depois`, ela vira `"[mascarado]"`.

- [ ] **Step 1: Escrever os testes que falham** — crie `tests/domain/test_audit.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import CAMPO_SENSIVEL, mascarar, registrar


def test_mascarar_remove_segredos_e_marca_mudanca() -> None:
    saida = mascarar(
        {
            "antes": {"nome": "antigo", "password": "segredo1"},
            "depois": {"nome": "novo", "password": "segredo2", "token": "abc"},
        }
    )
    assert saida["depois"] == {"nome": "novo", "password": "[mascarado]", "token": "[mascarado]"}
    assert saida["antes"] == {"nome": "antigo"}  # segredo removido, sem marca (não está no depois)
    assert "segredo" not in str(saida)


def test_mascarar_chave_sensivel_apenas_no_antes() -> None:
    saida = mascarar({"antes": {"senha_antiga": "x"}, "depois": {}})
    assert saida["antes"] == {}


def test_mascarar_nao_altera_os_dicts_originais() -> None:
    antes = {"password": "segredo"}
    depois = {"password": "outro"}
    saida = mascarar({"antes": antes, "depois": depois})
    assert saida["antes"] == {}
    assert saida["depois"] == {"password": "[mascarado]"}
    assert antes == {"password": "segredo"}
    assert depois == {"password": "outro"}


def test_registrar_grava_evento_com_details(db_session: Session) -> None:
    registrar(
        db_session,
        tipo="site.create",
        ator="cli",
        objeto="site",
        objeto_id=7,
        antes=None,
        depois={"name": "pop-spo-01"},
    )
    db_session.commit()

    (evento,) = db_session.scalars(select(models.AuditEvent))
    assert evento.type == "site.create"
    assert evento.actor == "cli"
    assert evento.details == {
        "objeto": "site",
        "objeto_id": 7,
        "antes": None,
        "depois": {"name": "pop-spo-01"},
    }


def test_registrar_mascara_sem_alterar_chamada_original(db_session: Session) -> None:
    depois = {"password": "outro"}
    registrar(db_session, tipo="x", ator="api", objeto="y", objeto_id=1, antes=None, depois=depois)
    db_session.commit()
    (evento,) = db_session.scalars(select(models.AuditEvent))
    assert evento.details["depois"] == {"password": "[mascarado]"}
    assert depois == {"password": "outro"}  # original intacto (mascarar copia)


def test_campos_sensiveis_listados() -> None:
    assert set(CAMPO_SENSIVEL) == {"password", "senha", "secret", "token"}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_audit.py -v`
Expected: FAIL — módulo `gerenet.domain.audit` inexistente.

- [ ] **Step 3: Implementar** — crie `src/gerenet/domain/audit.py`:

```python
"""Auditoria de CRUD — trilha imutável, sem segredos (§18).

Cada evento é um AuditEvent com type "<objeto>.<acao>" (ex.: "circuit.create",
"device.disable", "circuit.reserve") e details = {objeto, objeto_id, antes, depois}.
antes/depois carregam apenas os campos alterados; campos sensíveis (password,
senha, secret, token) nunca são gravados — quando alterados, viram "[mascarado]".
A tabela audit_events não recebe UPDATE nem DELETE em nenhum caminho de código.
"""
from collections.abc import Mapping

from sqlalchemy.orm import Session

from gerenet.domain import models

CAMPO_SENSIVEL = ("password", "senha", "secret", "token")


def mascarar(paineis: Mapping[str, dict | None]) -> dict[str, dict | None]:
    """Remove valores de campos sensíveis de antes/depois, sem alterar o input.

    Cada painel é copiado; chave sensível (substring case-insensitive de
    CAMPO_SENSIVEL) é removida de "antes" e vira "[mascarado]" em "depois"
    (sinaliza a mudança sem revelar o valor).
    """
    saida: dict[str, dict | None] = {}
    for painel, valores in paineis.items():
        if valores is None:
            saida[painel] = None
            continue
        copia = dict(valores)
        for chave in list(copia):
            if any(termo in chave.lower() for termo in CAMPO_SENSIVEL):
                copia.pop(chave)
                if painel == "depois":
                    copia[chave] = "[mascarado]"
        saida[painel] = copia
    return saida


def registrar(
    session: Session,
    *,
    tipo: str,
    ator: str,
    objeto: str,
    objeto_id: int,
    antes: dict | None = None,
    depois: dict | None = None,
) -> None:
    """Grava um evento de auditoria (sem commit — roda na transação da mudança)."""
    paineis = mascarar({"antes": antes, "depois": depois})
    session.add(
        models.AuditEvent(
            type=tipo,
            actor=ator,
            details={
                "objeto": objeto,
                "objeto_id": objeto_id,
                "antes": paineis["antes"],
                "depois": paineis["depois"],
            },
        )
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_audit.py -v`
Expected: PASS (6 testes).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/domain/audit.py tests/domain/test_audit.py
git commit -m "feat: auditoria de CRUD com mascaramento de segredos (domain/audit.py)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Retrofit de auditoria no CRUD de devices

**Files:**
- Modify: `src/gerenet/domain/services/devices.py` (`create_device`, `disable_device` ganham `*, actor`; auditoria)
- Modify: `src/gerenet/api/routers/devices.py` (`criar`, `atualizar` auditam; passam `actor`; mapeiam `ValidationError`)
- Modify: `src/gerenet/cli/devices.py` (`add`, `disable` passam `actor="cli"`)
- Modify: `tests/domain/test_devices_service.py`, `tests/api/test_devices_api.py` (assinaturas/eventos)
- Test: `tests/domain/test_devices_service.py` (eventos)

**Interfaces:**
- Consumes: `audit.registrar` (Task 4).
- Produces: `create_device(session, data, *, actor: str)` e `disable_device(session, device_id, *, actor: str)` — assinaturas finais, consumidas pelo router/CLI e por todas as tasks seguintes quando criarem devices de apoio. Tipos de evento: `device.create`, `device.update`, `device.disable`. `touch_collection` **não** audita (é coleta, não CRUD).

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/domain/test_devices_service.py` (o arquivo já importa `create_device`, `disable_device`, `DeviceCreate`; acrescente `from sqlalchemy import select` e `from gerenet.domain import models` se ainda não existirem):

```python
def test_criar_e_desativar_device_auditam(db_session: Session) -> None:
    dev = create_device(
        db_session,
        DeviceCreate(name="ne8k-aud", management_address="10.0.0.6"),
        actor="cli",
    )
    disable_device(db_session, dev.id, actor="cli")

    eventos = list(
        db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    )
    assert [e.type for e in eventos] == ["device.create", "device.disable"]
    assert eventos[0].actor == "cli"
    assert eventos[0].details["objeto"] == "device"
    assert eventos[0].details["objeto_id"] == dev.id
    assert eventos[0].details["antes"] is None
    assert "name" in eventos[0].details["depois"]
    assert eventos[1].details == {
        "objeto": "device",
        "objeto_id": dev.id,
        "antes": {"admin_status": True},
        "depois": {"admin_status": False},
    }


def test_disable_idempotente_nao_audita_duas_vezes(db_session: Session) -> None:
    dev = create_device(
        db_session, DeviceCreate(name="ne8k-aud2", management_address="10.0.0.8"), actor="cli"
    )
    disable_device(db_session, dev.id, actor="cli")
    disable_device(db_session, dev.id, actor="cli")  # no-op

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["device.create", "device.disable"]
```

**As chamadas antigas de `create_device`/`disable_device` neste arquivo precisam do `actor="cli"`** (Step 4 abaixo). Também em `tests/api/test_devices_api.py`, acrescente um teste que passa `db_session` (fixture do conftest) e confere os eventos gerados por POST e PATCH de desativação — **não há rota de auditoria até o Plano 3**, então a asserção é no banco:

```python
from sqlalchemy import select

from gerenet.domain import models


def test_post_e_patch_desativar_auditam(db_session: Session, client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r2-aud", "management_address": "10.0.0.5"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    dev_id = criado.json()["id"]
    desativado = client.patch(
        f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth()
    )
    assert desativado.status_code == 200

    tipos = [
        e.type
        for e in db_session.scalars(
            select(models.AuditEvent).order_by(models.AuditEvent.id)
        )
    ]
    assert tipos == ["device.create", "device.disable"]
    assert all(e.actor == "api" for e in db_session.scalars(select(models.AuditEvent)))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_devices_service.py tests/api/test_devices_api.py -v`
Expected: FAIL — `TypeError: create_device() got an unexpected keyword argument 'actor'`.

- [ ] **Step 3: Implementar**

Em `src/gerenet/domain/services/devices.py`, ajuste imports e o corpo de `create_device` (que hoje é `session.add` + `try/commit` com `IntegrityError → ConflictError`) para:

```python
from gerenet.domain.audit import registrar
```

```python
def create_device(session: Session, data: DeviceCreate, *, actor: str) -> models.Device:
    if data.asn is not None and not asn_valido(data.asn):
        raise ValidationError(f"ASN inválido ou reservado: {data.asn}.")
    dev = models.Device(**data.model_dump())
    session.add(dev)
    try:
        session.flush()  # define dev.id e valida unicidade antes da auditoria
        registrar(
            session,
            tipo="device.create",
            ator=actor,
            objeto="device",
            objeto_id=dev.id,
            antes=None,
            depois=data.model_dump(),
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Já existe um equipamento com esse nome.") from exc
    session.refresh(dev)
    return dev
```

e o `disable_device` (hoje `get` + `admin_status=False` + commit) para:

```python
def disable_device(session: Session, device_id: int, *, actor: str) -> models.Device:
    dev = get_device(session, device_id)
    if dev.admin_status is False:
        return dev  # idempotente: sem transição, sem evento (Ruling 5)
    dev.admin_status = False
    registrar(
        session,
        tipo="device.disable",
        ator=actor,
        objeto="device",
        objeto_id=dev.id,
        antes={"admin_status": True},
        depois={"admin_status": False},
    )
    session.commit()
    return dev
```

No router `src/gerenet/api/routers/devices.py` (o arquivo já importa `NotFoundError`/`ConflictError`; acrescente `ValidationError` e `registrar`):

```python
from gerenet.domain.audit import registrar
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
```

O corpo da rota `criar` passa a:

```python
@router.post("", response_model=DeviceOut, status_code=201)
def criar(data: DeviceCreate, session: SessionDep) -> object:
    try:
        return svc.create_device(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

E o corpo da rota `atualizar` (PATCH) passa a:

```python
@router.patch("/{device_id}", response_model=DeviceOut)
def atualizar(device_id: int, data: DeviceUpdate, session: SessionDep) -> object:
    try:
        dev = svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    mudancas = data.model_dump(exclude_unset=True)
    antes = {campo: getattr(dev, campo) for campo in mudancas}
    desativando = mudancas.get("admin_status") is False and set(mudancas) == {"admin_status"}
    registrar(
        session,
        tipo="device.disable" if desativando else "device.update",
        ator="api",
        objeto="device",
        objeto_id=dev.id,
        antes=antes,
        depois=mudancas,
    )
    for campo, valor in mudancas.items():
        setattr(dev, campo, valor)
    if desativando:
        dev.comm_status = "unknown"
    session.commit()
    session.refresh(dev)
    return dev
```

No CLI `src/gerenet/cli/devices.py`, a chamada de criação no comando `add` passa a:

```python
            dev = svc.create_device(
                session,
                DeviceCreate(
                    name=name,
                    management_address=address,
                    ssh_port=ssh_port,
                    model=model,
                    family=family,
                    role=role,
                    site_id=site_id,
                    asn=asn,
                ),
                actor="cli",
            )
```

e a chamada de desativação no comando `disable` passa a:

```python
        svc.disable_device(session, dev.id, actor="cli")
```

- [ ] **Step 4: Atualizar chamadas existentes nos testes**

Em `tests/domain/test_devices_service.py`, todas as chamadas atuais a `create_device(...)` e `disable_device(...)` ganham `actor="cli"` (ex.: `create_device(db_session, DeviceCreate(name="sw1-acesso", management_address="10.0.0.2", model="S6730"), actor="cli")`). Confira também `src/gerenet/cli/collect.py`, `src/gerenet/worker/` e coletores: se algum chamar `create_device`/`disable_device`, passe o `actor` apropriado — a suíte acusa se faltar.

Run: `uv run pytest tests/domain/test_devices_service.py tests/api/test_devices_api.py tests/domain/test_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte toda**

Run: `uv run pytest -v`
Expected: PASS (40+ testes).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/devices.py src/gerenet/api/routers/devices.py src/gerenet/cli/devices.py tests/
git commit -m "feat: auditoria no CRUD de devices (actor api/cli; PATCH admin_status=false vira disable)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: Alocador puro (IPAM §25.8) + settings de bloco

**Files:**
- Modify: `src/gerenet/config.py` (2 settings novos)
- Create: `src/gerenet/domain/services/ipam.py` (funções puras; o serviço transacional entra na Task 9, no mesmo arquivo)
- Test: `tests/domain/test_ipam.py`

**Interfaces:**
- Consumes: modelos `Site` (Task 2).
- Produces: em `gerenet.domain.services.ipam.py`:
  - `bloco_v4(site: models.Site) -> ipaddress.IPv4Network` — bloco do site ou settings `p2p_ipv4_block`;
  - `base_v6(site: models.Site) -> str` — base do site ou settings `p2p_ipv6_base` (forma `"2804:194C:1000::"`, sem `/48`);
  - `derivar_v6(ipv4: str) -> str` — sufixo em hextets (`"1100:73"`; Ruling 4: `ValidationError` se > 8 dígitos);
  - `_addr_v6(base: str, sufixo: str, host: int) -> str` — endereço montado (host 0 = rede do /126);
  - `pontas_v4(network: str) -> tuple[str, str]` — `(local, remota)` sem prefixo;
  - `pontas_v6(network: str) -> tuple[str, str]` — `(local, remota)` com `/126`.
  - Settings `p2p_ipv4_block: str = "100.64.0.0/10"` e `p2p_ipv6_base: str = "2804:194C:1000::/48"` (usados pelas Tasks 7 e 9 no default do site).

- [ ] **Step 1: Escrever os testes que falham** — crie `tests/domain/test_ipam.py`:

```python
from sqlalchemy.orm import Session

from gerenet.config import get_settings
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.ipam import (
    _addr_v6,
    base_v6,
    bloco_v4,
    derivar_v6,
    pontas_v4,
    pontas_v6,
)

import pytest
```

> Ajuste: `import pytest` no topo, antes do bloco de imports do `gerenet` (estilo do repo: stdlib, depois terceiros, depois locais). O arquivo deve começar com `import pytest` seguido dos imports acima em ordem.

```python
def test_bloco_v4_usa_override_do_site_e_settings() -> None:
    site = models.Site(name="pop-a", p2p_ipv4_block="100.64.0.0/24")
    assert str(bloco_v4(site)) == "100.64.0.0/24"
    assert str(bloco_v4(models.Site(name="pop-b"))) == "100.64.0.0/10"  # settings default
    assert get_settings().p2p_ipv6_base == "2804:194C:1000::/48"


def test_base_v6_sem_prefixo() -> None:
    site = models.Site(name="pop-a", p2p_ipv6_base="2804:194C:2000::/48")
    assert base_v6(site) == "2804:194C:2000::"


def test_derivar_v6_golden_da_spec() -> None:
    # §25.8 verbatim: 100.110.0.73 → octetos 2-4 = 110.0.73 → "110073" → "1100:73"
    assert derivar_v6("100.110.0.73") == "1100:73"


def test_derivar_v6_sufixo_curto_sem_zero_padding() -> None:
    assert derivar_v6("100.10.0.5") == "1005"    # "10"+"0"+"5" = "1005" (4 dígitos → 1 hextet)
    assert derivar_v6("100.2.3.4") == "234"      # "2"+"3"+"4" = "234" (hextet único)
    assert derivar_v6("100.64.0.1") == "6401"    # "64"+"0"+"1" = "6401" (4 dígitos → 1 hextet)


def test_derivar_v6_overflow_levanta_erro() -> None:
    # Ruling 4: 9 dígitos não cabem em 2 hextets (ex.: 100.127.255.255 → "127255255")
    with pytest.raises(ValidationError):
        derivar_v6("100.127.255.255")


def test_addr_v6_monta_enderecos_do_golden() -> None:
    assert _addr_v6("2804:194C:1000::", "1100:73", 1) == "2804:194C:1000::1100:73:1"
    assert _addr_v6("2804:194C:1000::", "1100:73", 2) == "2804:194C:1000::1100:73:2"
    assert _addr_v6("2804:194C:1000::", "", 1) == "2804:194C:1000::1"
    assert _addr_v6("2804:194C:1000::", "1005", 1) == "2804:194C:1000::1005:1"


def test_pontas_v4_31_e_30() -> None:
    assert pontas_v4("100.64.0.0/31") == ("100.64.0.0", "100.64.0.1")
    assert pontas_v4("100.64.0.2/31") == ("100.64.0.2", "100.64.0.3")
    assert pontas_v4("100.64.0.0/30") == ("100.64.0.1", "100.64.0.2")


def test_pontas_v6_derivam_dentro_do_126() -> None:
    local, remota = pontas_v6("2804:194C:1000::1100:73:0/126")
    assert local == "2804:194C:1000::1100:73:1/126"
    assert remota == "2804:194C:1000::1100:73:2/126"


def test_pontas_v6_roundtrip_golden_completo() -> None:
    """Do IPv4 do golden à rede v6 e às duas pontas (spec §6/§25.8)."""
    ipv4 = "100.110.0.73"
    sufixo = derivar_v6(ipv4)
    rede = f"{_addr_v6(base_v6(models.Site(name='pop')), sufixo, 0)}/126"
    assert rede == "2804:194C:1000::1100:73:0/126"
    local, remota = pontas_v6(rede)
    assert local == "2804:194C:1000::1100:73:1/126"
    assert remota == "2804:194C:1000::1100:73:2/126"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_ipam.py -v`
Expected: FAIL — módulo/settings inexistentes. (Se `test_bloco_v4_usa_override_do_site_e_settings` falhar só no assert de default porque o ambiente define `GERENET_P2P_IPV4_BLOCK`, o conftest `_reseta_settings` devolve os defaults a cada teste — confira que ele resetou antes de reclamar.)

- [ ] **Step 3: Implementar**

Em `src/gerenet/config.py`, adicione (após `lock_ttl_seconds`):

```python
    # IPAM p2p (§25.8): bloco privado de enlaces v4 e base v6 por padrão;
    # cada site pode sobrescrever.
    p2p_ipv4_block: str = "100.64.0.0/10"
    p2p_ipv6_base: str = "2804:194C:1000::/48"
```

Crie `src/gerenet/domain/services/ipam.py`:

```python
"""Alocador de enlace p2p (IPAM, §25.8).

Funções puras (sufixo IPv6, pontas, blocos); o serviço transacional
reservar_circuito entra na Task 9 — mesmo arquivo.
"""
import ipaddress

from gerenet.config import get_settings
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError


def bloco_v4(site: models.Site) -> ipaddress.IPv4Network:
    """Bloco de enlaces v4 do site (override) ou o default dos settings."""
    origem = site.p2p_ipv4_block or get_settings().p2p_ipv4_block
    return ipaddress.ip_network(origem, strict=False)


def base_v6(site: models.Site) -> str:
    """Base v6 do site (override) ou o default; forma '2804:194C:1000::'."""
    origem = site.p2p_ipv6_base or get_settings().p2p_ipv6_base
    return str(ipaddress.ip_network(origem, strict=False).network_address)


def derivar_v6(ipv4: str) -> str:
    """Sufixo do §25.8 a partir de um IPv4 de enlace.

    Octetos 2-4 concatenados sem zero-padding, relidos como dígitos hex e
    agrupados em hextets: grupo 1 = 4 primeiros dígitos, grupo 2 = o restante;
    grupo vazio é omitido. Ex.: 100.110.0.73 → "110.0.73" → dígitos "110073"
    → hextets "1100:73".
    """
    octetos = ipv4.split(".")
    if len(octetos) != 4:
        raise ValidationError(f"IPv4 inválido para derivação do sufixo: {ipv4}.")
    digitos = "".join(octetos[1:4])
    if len(digitos) > 8:
        raise ValidationError(
            f"O sufixo IPv6 derivado de {ipv4} excede 8 dígitos hex (limite de 2 hextets)."
        )
    if len(digitos) <= 4:
        return digitos
    return f"{digitos[:4]}:{digitos[4:]}"


def _addr_v6(base: str, sufixo: str, host: int) -> str:
    """Monta o endereço v6: base + hextets do sufixo + hextet de host.

    base termina em '::' (ex.: '2804:194C:1000::'). host = 0 produz a rede do
    /126 (bits de host zerados); host 1/2 produzem as pontas. Hextet final
    carrega os host bits nos 2 LSBs (spec §25.8).
    """
    corpo = f"{sufixo}:{host}" if sufixo else str(host)
    return f"{base}{corpo}"


def pontas_v4(network: str) -> tuple[str, str]:
    """Pontas local/remota de um enlace v4 (/31: .0/.1; /30: .1/.2)."""
    rede = ipaddress.ip_network(network, strict=True)
    base = int(rede.network_address)
    if rede.prefixlen == 31:
        return (str(ipaddress.IPv4Address(base)), str(ipaddress.IPv4Address(base + 1)))
    if rede.prefixlen == 30:
        return (str(ipaddress.IPv4Address(base + 1)), str(ipaddress.IPv4Address(base + 2)))
    raise ValidationError(f"Enlace p2p v4 deve ser /30 ou /31: {network}.")


def pontas_v6(network: str) -> tuple[str, str]:
    """Pontas local/remota de um /126 (rede +1/+2), com prefixo no retorno."""
    rede = ipaddress.ip_network(network, strict=True)
    if rede.prefixlen != 126:
        raise ValidationError(f"Enlace p2p v6 deve ser /126: {network}.")
    base = int(rede.network_address)
    return (
        f"{ipaddress.IPv6Address(base + 1)}/126",
        f"{ipaddress.IPv6Address(base + 2)}/126",
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_ipam.py -v`
Expected: PASS (10 testes) — confira o golden `100.110.0.73` → `1100:73` e o roundtrip `…::1100:73:0/126` → pontas `:1`/`:2`.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/config.py src/gerenet/domain/services/ipam.py tests/domain/test_ipam.py
git commit -m "feat: alocador puro IPAM §25.8 (sufixo v6, pontas, blocos) + settings p2p

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: Serviços de sites, organizações e contatos

**Files:**
- Create: `src/gerenet/domain/services/sites.py`, `organizations.py`, `contacts.py`
- Modify: `src/gerenet/domain/schemas.py` (schemas `Site*`, `Organization*`, `Contact*`)
- Test: `tests/domain/test_sites_service.py`, `test_organizations_service.py`, `test_contacts_service.py`

**Interfaces:**
- Consumes: `audit.registrar`, `validators.*`, modelos da Task 2.
- Produces:
  - `sites`: `create_site(session, data: SiteCreate, *, actor)`, `get_site(session, site_id)`, `list_sites(session, include_disabled=False)`, `update_site(session, site_id, data: SiteUpdate, *, actor)`, `disable_site(session, site_id, *, actor)`, `link_device(session, site_id, device_id, *, actor)`;
  - `organizations`: `create_organization(session, data: OrganizationCreate, *, actor)`, `get_organization`, `list_organizations(session, include_disabled=False, kind: str | None = None)`, `update_organization`, `disable_organization`;
  - `contacts`: `create_contact(session, data: ContactCreate, *, actor)`, `get_contact`, `list_contacts(session, organization_id=None)`, `update_contact`, `disable_contact`.
  - Erros: `NotFoundError` ("{Entidade} {id} não encontrad(o/a)."), `ConflictError` para duplicidade, `ValidationError` para dados.
  - Tipos de auditoria: `site.create|update|disable`, `site.link_device`, `organization.*`, `contact.*`.
  - A Task 8 consome `get_site`/`get_organization`; as Tasks 8 e 9 consomem `create_site`, `create_organization`, `create_device` e `link_device` nos testes.

- [ ] **Step 1: Escrever os schemas** — acrescente ao fim de `src/gerenet/domain/schemas.py` (e `from typing import Literal` junto aos imports de typing do topo, se ainda não existir):

```python
class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    city: str | None = Field(default=None, max_length=128)
    uf: str | None = Field(default=None, min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
    p2p_ipv4_block: str | None = Field(default=None, max_length=64)
    p2p_ipv6_base: str | None = Field(default=None, max_length=64)


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    city: str | None = Field(default=None, max_length=128)
    uf: str | None = Field(default=None, min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
    p2p_ipv4_block: str | None = Field(default=None, max_length=64)
    p2p_ipv6_base: str | None = Field(default=None, max_length=64)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    legal_name: str | None = Field(default=None, max_length=255)
    kind: Literal["downstream", "parceiro"] = "downstream"
    asn: int | None = Field(default=None, ge=1, le=4294967295)
    irr_as_set: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    legal_name: str | None = Field(default=None, max_length=255)
    kind: Literal["downstream", "parceiro"] | None = None
    asn: int | None = Field(default=None, ge=1, le=4294967295)
    irr_as_set: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class ContactCreate(BaseModel):
    organization_id: int
    name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    kind: Literal["tecnico", "noc", "admin"] = "tecnico"


class ContactUpdate(BaseModel):
    organization_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    kind: Literal["tecnico", "noc", "admin"] | None = None
```

- [ ] **Step 2: Escrever os testes que falham**

`tests/domain/test_sites_service.py`:

```python
import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import DeviceCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.sites import (
    create_site,
    disable_site,
    get_site,
    link_device,
    list_sites,
    update_site,
)


def test_cria_lista_e_desativa_site(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-spo-01", uf="SP"), actor="cli")
    assert site.name == "pop-spo-01"
    assert [s.name for s in list_sites(db_session)] == ["pop-spo-01"]

    disable_site(db_session, site.id, actor="cli")
    assert list_sites(db_session) == []
    assert [s.name for s in list_sites(db_session, include_disabled=True)] == ["pop-spo-01"]


def test_site_nome_duplicado_vira_conflito(db_session: Session) -> None:
    create_site(db_session, SiteCreate(name="pop-a"), actor="cli")
    with pytest.raises(ConflictError):
        create_site(db_session, SiteCreate(name="pop-a"), actor="cli")


def test_site_com_blocos_invalidos_rejeitado(db_session: Session) -> None:
    with pytest.raises(ValidationError):
        create_site(db_session, SiteCreate(name="pop-x", p2p_ipv4_block="300.0.0.0/24"), actor="cli")
    with pytest.raises(ValidationError):
        create_site(db_session, SiteCreate(name="pop-y", p2p_ipv6_base="2001::zz/48"), actor="cli")


def test_update_site_altera_campos(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-a", city="São Paulo"), actor="cli")
    atualizado = update_site(db_session, site.id, SiteUpdate(city="Campinas"), actor="cli")
    assert atualizado.city == "Campinas"


def test_link_device_valida_site_e_device(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-a"), actor="cli")
    dev = create_device(
        db_session, DeviceCreate(name="ne8k-link", management_address="10.0.0.9"), actor="cli"
    )
    dev = link_device(db_session, site.id, dev.id, actor="cli")
    assert dev.site_id == site.id
    with pytest.raises(NotFoundError):
        link_device(db_session, 9999, dev.id, actor="cli")
    with pytest.raises(NotFoundError):
        link_device(db_session, site.id, 9999, actor="cli")
```

`tests/domain/test_organizations_service.py`:

```python
import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import OrganizationCreate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import (
    create_organization,
    disable_organization,
    get_organization,
    list_organizations,
    update_organization,
)


def test_cria_lista_filtra_kind_e_desativa(db_session: Session) -> None:
    down = create_organization(
        db_session, OrganizationCreate(name="Provedor A", asn=64512), actor="cli"
    )
    parceiro = create_organization(
        db_session, OrganizationCreate(name="Parceiro B", kind="parceiro"), actor="cli"
    )
    assert [o.name for o in list_organizations(db_session, kind="downstream")] == ["Provedor A"]
    # ordem alfabética
    assert [o.name for o in list_organizations(db_session)] == ["Parceiro B", "Provedor A"]

    disable_organization(db_session, down.id, actor="cli")
    assert list_organizations(db_session, kind="downstream") == []


def test_asn_invalido_ou_reservado_rejeitado(db_session: Session) -> None:
    for asn in (23456, 4294967296):
        with pytest.raises(ValidationError):
            create_organization(db_session, OrganizationCreate(name="Org X", asn=asn), actor="cli")


def test_asn_duplicado_mesmo_desativado_vira_conflito(db_session: Session) -> None:
    org = create_organization(db_session, OrganizationCreate(name="Org A", asn=64512), actor="cli")
    disable_organization(db_session, org.id, actor="cli")
    with pytest.raises(ConflictError, match="ASN 64512"):
        create_organization(db_session, OrganizationCreate(name="Org B", asn=64512), actor="cli")


def test_update_organization_altera_e_rejeita_asn_em_uso(db_session: Session) -> None:
    org = create_organization(db_session, OrganizationCreate(name="Org A", asn=64512), actor="cli")
    atualizada = update_organization(
        db_session, org.id, OrganizationUpdate(legal_name="Provedor A LTDA"), actor="cli"
    )
    assert atualizada.legal_name == "Provedor A LTDA"

    create_organization(db_session, OrganizationCreate(name="Outra", asn=65001), actor="cli")
    with pytest.raises(ConflictError, match="ASN 65001"):
        update_organization(db_session, org.id, OrganizationUpdate(asn=65001), actor="cli")
```

`tests/domain/test_contacts_service.py`:

```python
import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import ContactCreate, OrganizationCreate
from gerenet.domain.services.contacts import (
    create_contact,
    disable_contact,
    get_contact,
    list_contacts,
    update_contact,
)
from gerenet.domain.services.errors import NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization


def _org(db_session: Session) -> int:
    return create_organization(db_session, OrganizationCreate(name="Org C", asn=64513), actor="cli").id


def test_cria_lista_por_organizacao_e_desativa(db_session: Session) -> None:
    org_id = _org(db_session)
    contato = create_contact(
        db_session,
        ContactCreate(organization_id=org_id, name="Fulano", email="noc@x.com.br"),
        actor="cli",
    )
    assert [c.name for c in list_contacts(db_session, organization_id=org_id)] == ["Fulano"]
    disable_contact(db_session, contato.id, actor="cli")
    assert get_contact(db_session, contato.id).admin_status is False


def test_contato_exige_organizacao_existente(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        create_contact(db_session, ContactCreate(organization_id=9999, name="X"), actor="cli")


def test_email_invalido_rejeitado(db_session: Session) -> None:
    org_id = _org(db_session)
    with pytest.raises(ValidationError, match="E-mail inválido"):
        create_contact(
            db_session, ContactCreate(organization_id=org_id, name="X", email="invalido"), actor="cli"
        )


def test_update_contact_muda_organizacao(db_session: Session) -> None:
    org_a = _org(db_session)
    org_b = create_organization(db_session, OrganizationCreate(name="Org D", asn=64514), actor="cli").id
    contato = create_contact(db_session, ContactCreate(organization_id=org_a, name="Fulano"), actor="cli")
    atualizado = update_contact(
        db_session, contato.id, ContactUpdate(organization_id=org_b, phone="11 99999-0000"), actor="cli"
    )
    assert atualizado.organization_id == org_b
    assert atualizado.phone == "11 99999-0000"
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_sites_service.py tests/domain/test_organizations_service.py tests/domain/test_contacts_service.py -v`
Expected: FAIL — módulos `services.sites` etc. inexistentes.

- [ ] **Step 4: Implementar os três serviços**

Crie `src/gerenet/domain/services/sites.py`:

```python
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import SiteCreate, SiteUpdate
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import ConflictError, NotFoundError
from gerenet.domain.validators import cidr_valido


def _valida_blocos(dump: dict) -> None:
    if dump.get("p2p_ipv4_block"):
        cidr_valido(dump["p2p_ipv4_block"], familia="ipv4")
    if dump.get("p2p_ipv6_base"):
        cidr_valido(dump["p2p_ipv6_base"], familia="ipv6")


def create_site(session: Session, data: SiteCreate, *, actor: str) -> models.Site:
    dump = data.model_dump()
    _valida_blocos(dump)
    site = models.Site(**dump)
    session.add(site)
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(
            session, tipo="site.create", ator=actor, objeto="site", objeto_id=site.id,
            antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe um site com o nome {data.name}.") from exc
    session.refresh(site)
    return site


def get_site(session: Session, site_id: int) -> models.Site:
    site = session.get(models.Site, site_id)
    if site is None:
        raise NotFoundError(f"Site {site_id} não encontrado.")
    return site


def list_sites(session: Session, include_disabled: bool = False) -> list[models.Site]:
    stmt = select(models.Site).order_by(models.Site.name)
    if not include_disabled:
        stmt = stmt.where(models.Site.admin_status.is_(True))
    return list(session.scalars(stmt))


def update_site(session: Session, site_id: int, data: SiteUpdate, *, actor: str) -> models.Site:
    site = get_site(session, site_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return site
    _valida_blocos(mudancas)
    antes = {campo: getattr(site, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(site, campo, valor)
    try:
        registrar(
            session, tipo="site.update", ator=actor, objeto="site", objeto_id=site.id,
            antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe um site com o nome {mudancas.get('name')}.") from exc
    session.refresh(site)
    return site


def disable_site(session: Session, site_id: int, *, actor: str) -> models.Site:
    site = get_site(session, site_id)
    if site.admin_status is False:
        return site
    site.admin_status = False
    registrar(
        session, tipo="site.disable", ator=actor, objeto="site", objeto_id=site.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return site


def link_device(session: Session, site_id: int, device_id: int, *, actor: str) -> models.Device:
    """Vincula um device ao site (idempotente; audita a intenção)."""
    site = get_site(session, site_id)
    dev = get_device(session, device_id)
    antes = {"site_id": dev.site_id}
    dev.site_id = site.id
    registrar(
        session, tipo="site.link_device", ator=actor, objeto="site", objeto_id=site.id,
        antes=antes, depois={"site_id": dev.site_id},
    )
    session.commit()
    session.refresh(dev)
    return dev
```

Crie `src/gerenet/domain/services/organizations.py`:

```python
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import OrganizationCreate, OrganizationUpdate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.validators import asn_valido


def _valida_asn(asn: int | None) -> None:
    if asn is not None and not asn_valido(asn):
        raise ValidationError(f"ASN inválido ou reservado: {asn}.")


def _confere_asn_livre(session: Session, asn: int | None, ignorando_id: int | None = None) -> None:
    """ASN é único mesmo entre desativados (§14.1)."""
    if asn is None:
        return
    stmt = select(models.Organization).where(models.Organization.asn == asn)
    if ignorando_id is not None:
        stmt = stmt.where(models.Organization.id != ignorando_id)
    if session.scalars(stmt).first() is not None:
        raise ConflictError(f"Já existe organização com ASN {asn}.")


def create_organization(
    session: Session, data: OrganizationCreate, *, actor: str
) -> models.Organization:
    dump = data.model_dump()
    _valida_asn(dump.get("asn"))
    _confere_asn_livre(session, dump.get("asn"))
    org = models.Organization(**dump)
    session.add(org)
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(
            session, tipo="organization.create", ator=actor, objeto="organization",
            objeto_id=org.id, antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe organização com o nome {data.name}.") from exc
    session.refresh(org)
    return org


def get_organization(session: Session, organization_id: int) -> models.Organization:
    org = session.get(models.Organization, organization_id)
    if org is None:
        raise NotFoundError(f"Organização {organization_id} não encontrada.")
    return org


def list_organizations(
    session: Session, include_disabled: bool = False, kind: str | None = None
) -> list[models.Organization]:
    stmt = select(models.Organization).order_by(models.Organization.name)
    if not include_disabled:
        stmt = stmt.where(models.Organization.admin_status.is_(True))
    if kind:
        stmt = stmt.where(models.Organization.kind == kind)
    return list(session.scalars(stmt))


def update_organization(
    session: Session, organization_id: int, data: OrganizationUpdate, *, actor: str
) -> models.Organization:
    org = get_organization(session, organization_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return org
    if "asn" in mudancas:
        _valida_asn(mudancas["asn"])
        _confere_asn_livre(session, mudancas["asn"], ignorando_id=org.id)
    antes = {campo: getattr(org, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(org, campo, valor)
    try:
        registrar(
            session, tipo="organization.update", ator=actor, objeto="organization",
            objeto_id=org.id, antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe organização com o nome {mudancas.get('name')}.") from exc
    session.refresh(org)
    return org


def disable_organization(session: Session, organization_id: int, *, actor: str) -> models.Organization:
    org = get_organization(session, organization_id)
    if org.admin_status is False:
        return org
    org.admin_status = False
    registrar(
        session, tipo="organization.disable", ator=actor, objeto="organization",
        objeto_id=org.id, antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return org
```

Crie `src/gerenet/domain/services/contacts.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import ContactCreate, ContactUpdate
from gerenet.domain.services.errors import NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.validators import email_valido


def create_contact(session: Session, data: ContactCreate, *, actor: str) -> models.Contact:
    get_organization(session, data.organization_id)  # NotFoundError com mensagem PT
    if data.email and not email_valido(data.email):
        raise ValidationError(f"E-mail inválido: {data.email}.")
    dump = data.model_dump()
    contato = models.Contact(**dump)
    session.add(contato)
    session.flush()
    registrar(
        session, tipo="contact.create", ator=actor, objeto="contact", objeto_id=contato.id,
        antes=None, depois=dump,
    )
    session.commit()
    session.refresh(contato)
    return contato


def get_contact(session: Session, contact_id: int) -> models.Contact:
    contato = session.get(models.Contact, contact_id)
    if contato is None:
        raise NotFoundError(f"Contato {contact_id} não encontrado.")
    return contato


def list_contacts(session: Session, organization_id: int | None = None) -> list[models.Contact]:
    stmt = select(models.Contact).order_by(models.Contact.name)
    if organization_id is not None:
        stmt = stmt.where(models.Contact.organization_id == organization_id)
    return list(session.scalars(stmt))


def update_contact(session: Session, contact_id: int, data: ContactUpdate, *, actor: str) -> models.Contact:
    contato = get_contact(session, contact_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return contato
    if mudancas.get("organization_id"):
        get_organization(session, mudancas["organization_id"])
    if mudancas.get("email") and not email_valido(mudancas["email"]):
        raise ValidationError(f"E-mail inválido: {mudancas['email']}.")
    antes = {campo: getattr(contato, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(contato, campo, valor)
    registrar(
        session, tipo="contact.update", ator=actor, objeto="contact", objeto_id=contato.id,
        antes=antes, depois=mudancas,
    )
    session.commit()
    session.refresh(contato)
    return contato


def disable_contact(session: Session, contact_id: int, *, actor: str) -> models.Contact:
    contato = get_contact(session, contact_id)
    if contato.admin_status is False:
        return contato
    contato.admin_status = False
    registrar(
        session, tipo="contact.disable", ator=actor, objeto="contact", objeto_id=contato.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return contato
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_sites_service.py tests/domain/test_organizations_service.py tests/domain/test_contacts_service.py -v`
Expected: PASS (13 testes).

- [ ] **Step 6: Rodar a suíte toda**

Run: `uv run pytest -v`
Expected: PASS (suíte completa).

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/services/sites.py src/gerenet/domain/services/organizations.py src/gerenet/domain/services/contacts.py src/gerenet/domain/schemas.py tests/domain/
git commit -m "feat: serviços de sites, organizações e contatos com auditoria

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: Serviço de circuitos

**Files:**
- Create: `src/gerenet/domain/services/circuits.py`
- Modify: `src/gerenet/domain/schemas.py` (schemas `CircuitCreate`/`CircuitUpdate` — o `Literal` já foi importado na Task 7, não duplique)
- Test: `tests/domain/test_circuits_service.py`

**Interfaces:**
- Consumes: `get_site` (sites), `get_organization` (organizations), `get_device` (devices F1).
- Produces: `create_circuit(session, data: CircuitCreate, *, actor)`, `get_circuit(session, circuit_id)`, `list_circuits(session, organization_id=None, site_id=None, include_disabled=False)`, `update_circuit(session, circuit_id, data: CircuitUpdate, *, actor)`, `disable_circuit(session, circuit_id, *, actor)` — valida: `code` único; `access_device`/`edge_device`/`backup_edge_device` **pertencem ao `site_id`** (create e update — em update de `site_id`, revalida também os devices atuais); auditoria `circuit.create|update|disable`. A Task 9 consome `get_circuit`, `create_circuit`, `disable_circuit` e o modelo `Circuit`.

- [ ] **Step 1: Escrever os schemas** — acrescente a `src/gerenet/domain/schemas.py`:

```python
class CircuitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    organization_id: int
    site_id: int
    access_device_id: int
    access_port: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9/\-]+$")
    edge_device_id: int
    backup_edge_device_id: int | None = None
    stack: Literal["ipv4", "ipv6", "dual"] = "dual"
    vlan_mode: Literal["unica", "separada"] = "unica"
    qinq: bool = False
    vrf: str | None = Field(default=None, max_length=64)
    mtu: int | None = Field(default=None, ge=576, le=9600)
    bandwidth: str | None = Field(default=None, max_length=32)
    bfd: bool = False
    p2p_v4_len: Literal[30, 31] = 31
    description: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class CircuitUpdate(BaseModel):
    organization_id: int | None = None
    site_id: int | None = None
    access_device_id: int | None = None
    access_port: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9/\-]+$")
    edge_device_id: int | None = None
    backup_edge_device_id: int | None = None
    stack: Literal["ipv4", "ipv6", "dual"] | None = None
    vlan_mode: Literal["unica", "separada"] | None = None
    qinq: bool | None = None
    vrf: str | None = Field(default=None, max_length=64)
    mtu: int | None = Field(default=None, ge=576, le=9600)
    bandwidth: str | None = Field(default=None, max_length=32)
    bfd: bool | None = None
    p2p_v4_len: Literal[30, 31] | None = None
    description: str | None = Field(default=None, max_length=255)
    notes: str | None = None
```

- [ ] **Step 2: Escrever os testes que falham** — crie `tests/domain/test_circuits_service.py`:

```python
import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import CircuitCreate, CircuitUpdate, DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.circuits import (
    create_circuit,
    disable_circuit,
    get_circuit,
    list_circuits,
    update_circuit,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session) -> tuple[int, int, int, int, int]:
    """Site + organização + switch e 2 NE8000 vinculados; devolve os ids."""
    site = create_site(db_session, SiteCreate(name="pop-spo-01"), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="Cliente X", asn=64512), actor="cli")
    sw = create_device(db_session, DeviceCreate(name="sw1", management_address="10.0.0.2"), actor="cli")
    ne = create_device(db_session, DeviceCreate(name="ne8k", management_address="10.0.0.1"), actor="cli")
    ne8k2 = create_device(db_session, DeviceCreate(name="ne8k2", management_address="10.0.0.3"), actor="cli")
    link_device(db_session, site.id, sw.id, actor="cli")
    link_device(db_session, site.id, ne.id, actor="cli")
    link_device(db_session, site.id, ne8k2.id, actor="cli")
    return org.id, site.id, sw.id, ne.id, ne8k2.id


def _circuito(
    site_id: int, org_id: int, sw_id: int, ne_id: int, *, code: str = "CIRC-0001", **extra,
) -> CircuitCreate:
    base = dict(
        code=code, organization_id=org_id, site_id=site_id,
        access_device_id=sw_id, access_port="GE0/0/1", edge_device_id=ne_id,
    )
    base.update(extra)
    return CircuitCreate(**base)


def test_cria_lista_e_desativa_circuito(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    circ = create_circuit(
        db_session, _circuito(site_id, org_id, sw_id, ne_id), actor="cli"
    )
    assert circ.stack == "dual"
    assert [c.code for c in list_circuits(db_session)] == ["CIRC-0001"]

    disable_circuit(db_session, circ.id, actor="cli")
    assert list_circuits(db_session) == []
    assert [c.code for c in list_circuits(db_session, include_disabled=True)] == ["CIRC-0001"]


def test_circuito_code_duplicado_vira_conflito(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    create_circuit(db_session, _circuito(site_id, org_id, sw_id, ne_id), actor="cli")
    with pytest.raises(ConflictError, match="CIRC-0001"):
        create_circuit(db_session, _circuito(site_id, org_id, sw_id, ne_id), actor="cli")


def test_device_fora_do_site_rejeitado(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    outro_site = create_site(db_session, SiteCreate(name="pop-rj-01"), actor="cli")
    ne_fora = create_device(db_session, DeviceCreate(name="ne8k-fora", management_address="10.0.0.4"), actor="cli")
    link_device(db_session, outro_site.id, ne_fora.id, actor="cli")
    dados = _circuito(site_id, org_id, sw_id, ne_id, backup_edge_device_id=ne_fora.id)
    with pytest.raises(ValidationError, match="não pertence ao site"):
        create_circuit(db_session, dados, actor="cli")


def test_device_sem_site_rejeitado(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    solto = create_device(db_session, DeviceCreate(name="ne8k-solto", management_address="10.0.0.5"), actor="cli")
    dados = _circuito(site_id, org_id, sw_id, ne_id, backup_edge_device_id=solto.id)
    with pytest.raises(ValidationError, match="não pertence ao site"):
        create_circuit(db_session, dados, actor="cli")


def test_update_circuito_revalida_vinculos(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, ne8k2_id = _ambiente(db_session)
    circ = create_circuit(db_session, _circuito(site_id, org_id, sw_id, ne_id), actor="cli")
    atualizado = update_circuit(
        db_session, circ.id,
        CircuitUpdate(edge_device_id=ne8k2_id, description="circuito principal"),
        actor="cli",
    )
    assert atualizado.edge_device_id == ne8k2_id
    # troca de site exige devices do novo site — os atuais ficam de fora → erro
    outro_site = create_site(db_session, SiteCreate(name="pop-rj-02"), actor="cli")
    with pytest.raises(ValidationError, match="não pertence ao site"):
        update_circuit(db_session, circ.id, CircuitUpdate(site_id=outro_site.id), actor="cli")


def test_get_circuito_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        get_circuit(db_session, 9999)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_circuits_service.py -v`
Expected: FAIL — módulo `services.circuits` inexistente.

- [ ] **Step 4: Implementar** — crie `src/gerenet/domain/services/circuits.py`:

```python
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import CircuitCreate, CircuitUpdate
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.services.sites import get_site

_CAMPOS_DEVICE = ("access_device_id", "edge_device_id", "backup_edge_device_id")


def _valida_vinculos(session: Session, site_id: int, dump: dict) -> None:
    """access/edge/backup devem pertencer ao site do circuito (spec)."""
    get_site(session, site_id)  # NotFoundError com mensagem PT
    for campo in _CAMPOS_DEVICE:
        device_id = dump.get(campo)
        if device_id is None:
            continue
        dev = get_device(session, device_id)
        if dev.site_id != site_id:
            raise ValidationError(f"Equipamento {dev.name} não pertence ao site {site_id}.")


def create_circuit(session: Session, data: CircuitCreate, *, actor: str) -> models.Circuit:
    get_organization(session, data.organization_id)
    dump = data.model_dump()
    _valida_vinculos(session, data.site_id, dump)
    circ = models.Circuit(**dump)
    session.add(circ)
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(
            session, tipo="circuit.create", ator=actor, objeto="circuit", objeto_id=circ.id,
            antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe um circuito com o código {data.code}.") from exc
    session.refresh(circ)
    return circ


def get_circuit(session: Session, circuit_id: int) -> models.Circuit:
    circ = session.get(models.Circuit, circuit_id)
    if circ is None:
        raise NotFoundError(f"Circuito {circuit_id} não encontrado.")
    return circ


def list_circuits(
    session: Session,
    organization_id: int | None = None,
    site_id: int | None = None,
    include_disabled: bool = False,
) -> list[models.Circuit]:
    stmt = select(models.Circuit).order_by(models.Circuit.code)
    if not include_disabled:
        stmt = stmt.where(models.Circuit.admin_status.is_(True))
    if organization_id is not None:
        stmt = stmt.where(models.Circuit.organization_id == organization_id)
    if site_id is not None:
        stmt = stmt.where(models.Circuit.site_id == site_id)
    return list(session.scalars(stmt))


def update_circuit(session: Session, circuit_id: int, data: CircuitUpdate, *, actor: str) -> models.Circuit:
    circ = get_circuit(session, circuit_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return circ
    if mudancas.get("organization_id"):
        get_organization(session, mudancas["organization_id"])
    novo_site_id = mudancas.get("site_id", circ.site_id)
    vinculos = dict(mudancas)
    if "site_id" in mudancas and mudancas["site_id"] != circ.site_id:
        # troca de site: revalida também os devices atuais contra o novo site
        for campo in _CAMPOS_DEVICE:
            vinculos.setdefault(campo, getattr(circ, campo))
    _valida_vinculos(session, novo_site_id, vinculos)
    antes = {campo: getattr(circ, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(circ, campo, valor)
    try:
        registrar(
            session, tipo="circuit.update", ator=actor, objeto="circuit", objeto_id=circ.id,
            antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe um circuito com o código {mudancas.get('code')}.") from exc
    session.refresh(circ)
    return circ


def disable_circuit(session: Session, circuit_id: int, *, actor: str) -> models.Circuit:
    circ = get_circuit(session, circuit_id)
    if circ.admin_status is False:
        return circ
    circ.admin_status = False
    registrar(
        session, tipo="circuit.disable", ator=actor, objeto="circuit", objeto_id=circ.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return circ
```

> Semântica do `_valida_vinculos` no update: valida apenas os campos presentes no `vinculos` (`None` nos demais é ignorado) — quando só `description` muda, nenhum device é revalidado. Quando `site_id` muda, os devices atuais entram no `vinculos` e são conferidos contra o novo site.

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_circuits_service.py -v`
Expected: PASS (6 testes).

- [ ] **Step 6: Rodar a suíte toda**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/services/circuits.py src/gerenet/domain/schemas.py tests/domain/test_circuits_service.py
git commit -m "feat: serviço de circuitos com vínculo de devices ao site e auditoria

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: Reserva de circuito (`reservar_circuito`) — idempotente, com VLANs e p2p v4/v6

**Files:**
- Modify: `src/gerenet/domain/services/ipam.py` (função transacional + helpers de alocação, acrescentados ao arquivo da Task 6)
- Test: `tests/domain/test_reserva_circuito.py`

**Interfaces:**
- Consumes: puras da Task 6 (`bloco_v4`, `base_v6`, `derivar_v6`, `_addr_v6`), `get_circuit`/`disable_circuit` (Task 8), `validar_vid` (Task 1).
- Produces: `reservar_circuito(session, circuit_id, *, actor) -> models.Circuit` — grava `vlans` (1 linha `unica`/family `NULL`, ou 2 em `separada` com `family` v4/v6; `kind="s_vlan"` quando `qinq`) e `ip_prefixes` (p2p v4 `/p2p_v4_len`; p2p v6 `/126` derivado do v4; `stack=ipv6` reserva também o par v4 de derivação anotado em `notes`); **idempotente** (circuito já com VLAN reservada ⇒ devolve como está e audita `circuit.reserve` com `depois={"repetida": True}`); auditoria `circuit.reserve` com os valores alocados; erros: `NotFoundError` (circuito inexistente, via `get_circuit`), `ConflictError` ("Circuito {code} desativado não recebe reservas.", "Bloco p2p do site esgotado.", e o guard do Ruling 7 com mensagem de sufixo v6 já reservado).

- [ ] **Step 1: Escrever os testes que falham** — crie `tests/domain/test_reserva_circuito.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.circuits import create_circuit, disable_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session, bloco: str = "100.64.0.0/24") -> tuple[int, int]:
    """Site (bloco p2p override) + org + switch/NE8000 vinculados + circuito; devolve (site_id, circuit_id)."""
    site = create_site(db_session, SiteCreate(name="pop-spo-01", p2p_ipv4_block=bloco), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="Cliente X", asn=64512), actor="cli")
    sw = create_device(db_session, DeviceCreate(name="sw1", management_address="10.0.0.2"), actor="cli")
    ne = create_device(db_session, DeviceCreate(name="ne8k", management_address="10.0.0.1"), actor="cli")
    link_device(db_session, site.id, sw.id, actor="cli")
    link_device(db_session, site.id, ne.id, actor="cli")
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0001", organization_id=org.id, site_id=site.id,
            access_device_id=sw.id, access_port="GE0/0/1", edge_device_id=ne.id,
        ),
        actor="cli",
    )
    return site.id, circ.id


def test_reserva_dual_cria_vlan_e_p2p_v4_v6(db_session: Session) -> None:
    site_id, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor="cli")

    vlans = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id)))
    prefixos = list(
        db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    )
    assert len(vlans) == 1
    assert vlans[0].site_id == site_id
    assert 2 <= vlans[0].vid <= 4094
    assert vlans[0].family is None  # unica: VLAN sem família

    v4 = [p for p in prefixos if "." in p.network]
    v6 = [p for p in prefixos if ":" in p.network]
    assert len(v4) == 1 and len(v6) == 1
    assert v4[0].network.endswith("/31")
    assert v6[0].network.endswith("/126")


def test_reserva_v6_deriva_do_v4_escolhido(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor="cli")

    (rede_v4,) = db_session.scalars(
        select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id, models.IpPrefix.network.like("100.64.%"))
    )
    (rede_v6,) = db_session.scalars(
        select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id, models.IpPrefix.network.like("%:%/%"))
    )
    # v4 primeiro livre do bloco 100.64.0.0/24 = 100.64.0.0/31 → sufixo "6400"
    assert rede_v4.network == "100.64.0.0/31"
    assert rede_v6.network == "2804:194C:1000::6400:0/126"


def test_reserva_idempotente_nao_duplica(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor="cli")
    reservar_circuito(db_session, circ_id, actor="cli")  # 2ª chamada: no-op

    vlans = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id)))
    prefixos = list(
        db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    )
    assert len(vlans) == 1 and len(prefixos) == 2
    eventos = list(
        db_session.scalars(
            select(models.AuditEvent)
            .where(models.AuditEvent.type == "circuit.reserve")
            .order_by(models.AuditEvent.id)
        )
    )
    assert len(eventos) == 2
    assert eventos[1].details["depois"] == {"repetida": True}


def test_reserva_vlan_separada_cria_duas_vlans_por_familia(db_session: Session) -> None:
    site_id, circ_id = _ambiente(db_session)
    circ = db_session.get(models.Circuit, circ_id)
    circ.vlan_mode = "separada"
    db_session.commit()
    reservar_circuito(db_session, circ_id, actor="cli")

    vlans = list(
        db_session.scalars(
            select(models.Vlan)
            .where(models.Vlan.circuit_id == circ_id)
            .order_by(models.Vlan.family)
        )
    )
    assert [v.family for v in vlans] == ["ipv4", "ipv6"]
    assert len({v.vid for v in vlans}) == 2
    assert vlans[0].site_id == site_id


def test_reserva_qinq_marca_s_vlan(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    circ = db_session.get(models.Circuit, circ_id)
    circ.qinq = True
    db_session.commit()
    reservar_circuito(db_session, circ_id, actor="cli")
    (vlan,) = db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id))
    assert vlan.kind == "s_vlan"


def test_reserva_stack_ipv6_reserva_v4_de_derivacao(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    circ = db_session.get(models.Circuit, circ_id)
    circ.stack = "ipv6"
    db_session.commit()
    reservar_circuito(db_session, circ_id, actor="cli")

    prefixos = list(
        db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    )
    assert len(prefixos) == 2  # v4 (derivação) + v6
    v4 = [p for p in prefixos if "." in p.network][0]
    assert "deriva" in (v4.notes or "").lower()
    v6 = [p for p in prefixos if ":" in p.network][0]
    assert v6.network.endswith("/126")


def test_reserva_esgota_bloco_do_site(db_session: Session) -> None:
    """Bloco /30 do site comporta 2 enlaces /31; a 3ª reserva estoura."""
    site_id, circ1_id = _ambiente(db_session, bloco="100.64.0.0/30")
    org_id = db_session.get(models.Circuit, circ1_id).organization_id
    sw2 = create_device(db_session, DeviceCreate(name="sw2", management_address="10.0.0.6"), actor="cli")
    ne3 = create_device(db_session, DeviceCreate(name="ne8k3", management_address="10.0.0.7"), actor="cli")
    link_device(db_session, site_id, sw2.id, actor="cli")
    link_device(db_session, site_id, ne3.id, actor="cli")
    circ2 = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0002", organization_id=org_id, site_id=site_id,
            access_device_id=sw2.id, access_port="GE0/0/2", edge_device_id=ne3.id,
        ),
        actor="cli",
    )
    circ3 = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0003", organization_id=org_id, site_id=site_id,
            access_device_id=sw2.id, access_port="GE0/0/3", edge_device_id=ne3.id,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ2.id, actor="cli")
    reservar_circuito(db_session, circ3.id, actor="cli")
    with pytest.raises(ConflictError, match="esgotado"):
        reservar_circuito(db_session, circ1_id, actor="cli")


def test_reserva_circuito_desativado_rejeitado(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    disable_circuit(db_session, circ_id, actor="cli")
    with pytest.raises(ConflictError, match="desativado"):
        reservar_circuito(db_session, circ_id, actor="cli")


def test_reserva_v6_derivada_duplicada_rejeitada(db_session: Session) -> None:
    """Ruling 7: sufixo v6 já reservado no site falha com erro claro.

    O primeiro v4 livre de 100.64.0.0/24 é 100.64.0.0/31 → sufixo "6400" →
    rede ...::6400:0/126. Pré-ocupamos essa rede v6 e a reserva deve falhar
    em vez de violar o UNIQUE(site_id, network).
    """
    site_id, circ_id = _ambiente(db_session)
    derivada = "2804:194C:1000::6400:0/126"
    db_session.add(models.IpPrefix(site_id=site_id, network=derivada, kind="p2p"))
    db_session.commit()
    with pytest.raises(ConflictError, match="já reservado"):
        reservar_circuito(db_session, circ_id, actor="cli")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_reserva_circuito.py -v`
Expected: FAIL — `reservar_circuito` inexistente.

- [ ] **Step 3: Implementar** — acrescente ao arquivo `src/gerenet/domain/services/ipam.py`, **junto dos imports do topo** (que hoje têm `ipaddress`, `get_settings`, `models`, `ValidationError`), estes novos imports:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain.audit import registrar
from gerenet.domain.services.circuits import get_circuit
from gerenet.domain.services.errors import ConflictError
from gerenet.domain.validators import validar_vid
```

E, no fim do arquivo, acrescente:

```python
def _primeiro_vid(session: Session, site_id: int, ignorar: set[int] | None = None) -> int:
    """Menor VID 2-4094 não reservado no site (Ruling 6: só linhas existentes)."""
    ocupados = set(session.scalars(select(models.Vlan.vid).where(models.Vlan.site_id == site_id)))
    if ignorar:
        ocupados |= ignorar
    for vid in range(2, 4095):
        if vid not in ocupados:
            validar_vid(vid)
            return vid
    raise ConflictError("VLANs esgotadas neste site.")


def _primeiro_livre(session: Session, site: models.Site, comprimento: int) -> ipaddress.IPv4Network:
    """Próximo prefixo v4 livre no bloco do site (first-fit, sem sobreposição)."""
    bloco = bloco_v4(site)
    ocupadas = [
        ipaddress.ip_network(linha, strict=True)
        for linha in session.scalars(
            select(models.IpPrefix.network).where(models.IpPrefix.site_id == site.id)
        )
    ]
    for candidata in bloco.subnets(new_prefix=comprimento):
        if not any(candidata.overlaps(existente) for existente in ocupadas):
            return candidata
    raise ConflictError("Bloco p2p do site esgotado.")


def reservar_circuito(session: Session, circuit_id: int, *, actor: str) -> models.Circuit:
    """Reserva VLAN(s) e enlace(s) p2p do circuito — idempotente (§3.2).

    Circuito já reservado ⇒ devolve o estado atual e audita como no-op.
    stack: ipv4 ⇒ só v4; dual ⇒ v4 + v6 derivado; ipv6 ⇒ v4 interno de
    derivação (anotado em notes) + v6 (spec). Primeira alocação é
    transacional: falha antes do add_all ⇒ nenhuma linha parcial.
    """
    circ = get_circuit(session, circuit_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe reservas.")
    ja_reservado = (
        session.scalars(
            select(models.Vlan.id).where(models.Vlan.circuit_id == circ.id).limit(1)
        ).first()
        is not None
    )
    if ja_reservado:
        registrar(
            session, tipo="circuit.reserve", ator=actor, objeto="circuit",
            objeto_id=circ.id, antes=None, depois={"repetida": True},
        )
        session.commit()
        return circ

    site = session.get(models.Site, circ.site_id)
    vlans: list[models.Vlan] = []
    prefixos: list[models.IpPrefix] = []

    # VLANs: 1 linha (unica) ou 2 por família (separada); kind s_vlan no QinQ
    familias: list[str | None] = [None]
    if circ.vlan_mode == "separada":
        familias = ["ipv4", "ipv6"]
    vids_reservados: set[int] = set()
    for familia in familias:
        vid = _primeiro_vid(session, circ.site_id, vids_reservados)
        vids_reservados.add(vid)
        vlans.append(
            models.Vlan(
                site_id=circ.site_id,
                vid=vid,
                kind="s_vlan" if circ.qinq else "vlan",
                family=familia,
                circuit_id=circ.id,
                status="reservada",
            )
        )

    # Enlace p2p v4 (+ v6 derivado quando dual/ipv6)
    precisa_v4 = circ.stack in ("ipv4", "dual", "ipv6")  # ipv6: só p/ derivar o sufixo
    rede_v4: ipaddress.IPv4Network | None = None
    if precisa_v4:
        rede_v4 = _primeiro_livre(session, site, circ.p2p_v4_len)
        prefixos.append(
            models.IpPrefix(
                site_id=circ.site_id,
                network=str(rede_v4),
                kind="p2p",
                circuit_id=circ.id,
                notes=(
                    "Par v4 interno — derivação do sufixo IPv6 (§25.8)."
                    if circ.stack == "ipv6"
                    else None
                ),
            )
        )
    if circ.stack in ("dual", "ipv6"):
        if rede_v4 is None:  # defesa: dual/ipv6 sempre passam pelo v4 acima
            raise ConflictError("Reserva v6 exige o par v4 de derivação.")
        sufixo = derivar_v6(str(rede_v4.network_address))
        rede_v6 = f"{_addr_v6(base_v6(site), sufixo, 0)}/126"
        # Ruling 7: concatenação decimal não é injetiva — falha clara em vez de UNIQUE
        ja_existe = (
            session.scalars(
                select(models.IpPrefix.network).where(
                    models.IpPrefix.site_id == circ.site_id,
                    models.IpPrefix.network == rede_v6,
                )
            ).first()
            is not None
        )
        if ja_existe:
            raise ConflictError(
                f"Enlace v6 {rede_v6} (derivado de {rede_v4.network_address}) já reservado neste site."
            )
        prefixos.append(
            models.IpPrefix(
                site_id=circ.site_id,
                network=rede_v6,
                kind="p2p",
                circuit_id=circ.id,
            )
        )

    session.add_all(vlans + prefixos)
    session.flush()
    registrar(
        session, tipo="circuit.reserve", ator=actor, objeto="circuit", objeto_id=circ.id,
        antes=None,
        depois={
            "vlans": [{"vid": v.vid, "kind": v.kind, "family": v.family} for v in vlans],
            "ip_prefixes": [{"network": p.network} for p in prefixos],
        },
    )
    session.commit()
    session.refresh(circ)
    return circ
```

> Os conflitos (`_primeiro_livre`, guard do Ruling 7, circuito desativado) levantam **antes** do `session.add_all`/flush — reserva falha sem linha parcial e sem evento de auditoria. O commit do `ja_reservado` (no-op) é o único caminho que registra sem alocar nada.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_reserva_circuito.py -v`
Expected: PASS (9 testes).

- [ ] **Step 5: Rodar a suíte toda**

Run: `uv run pytest -v`
Expected: PASS (suíte completa verde).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/ipam.py tests/domain/test_reserva_circuito.py
git commit -m "feat: reservar_circuito idempotente (VLANs + p2p v4/v6 §25.8) com auditoria

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-review do plano

- **Cobertura da spec (seções):** modelo de dados → Task 2; regras de domínio (ASN/VID/CIDR/unicidades/vínculo) → Tasks 1, 3, 7, 8; alocador p2p → Tasks 6 e 9; auditoria → Tasks 4 e 5; API/CLI nova e endpoints de auditoria → Plano 3 (fatiamento declarado); soft-delete/unicidade §14.1 → Tasks 2, 7, 8; §25.8 golden → Tasks 6 e 9 (verbatim `100.110.0.73` → `…::1100:73:0/126`).
- **Débitos anotados (para o ledger):** guard de colisão do sufixo §25.8 sem skip (Ruling 7, ciclo C); CLI/API da nova SoT no Plano 3; password BGP no Plano 2; mapeamento HTTP de `ValidationError` (400) só onde há rota hoje (devices); `gerenet.cli.devices.disable` continua resolvendo por nome → `--site-id`/`--asn` não alteram lookup.
- **Sem placeholders:** todas as steps têm código/valores exatos; nenhum "TBD/TODO".

## Próximos planos do ciclo A

- **Plano 2 — Sessões BGP e políticas**: tabelas `bgp_sessions`, `bgp_policy_profiles` (catálogo §25.5), `communities` + `bgp_session_communities`, `bgp_prefix_authorizations`; segunda migration; serviços com as regras de unicidade §14.1; seeds de produtos; password BGP no Vault (`password_ref`/`has_password`).
- **Plano 3 — API e CLI**: routers `/api/v1/{sites,organizations,downstreams,contacts,circuits,bgp-sessions,prefix-authorizations,policy-profiles,audit-events}` com schemas `*Out` (incl. pontas derivadas no GET de circuito) + sub-apps do CLI + smoke de API/CLI.
