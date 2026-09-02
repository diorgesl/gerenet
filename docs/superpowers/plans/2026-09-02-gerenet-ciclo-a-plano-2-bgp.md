# Ciclo A — Plano 2: Sessões BGP, prefixos autorizados, produtos de roteamento e communities

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar as tabelas e serviços BGP do ciclo A da Source of Truth de downstreams: `bgp_sessions` com o modelo completo §6.3 e as regras de unicidade do §14.1, `bgp_prefix_authorizations` (origem manual) com a regra de sobreposição entre organizações, e os catálogos seedados `bgp_policy_profiles` (6 produtos de exportação §25.5) e `communities` (3 seeds §25.6) com associação auditada a sessões.

**Architecture:** Segue o padrão dos Planos 1/F1 já implementados: modelos SQLAlchemy em `domain/models.py`, serviços com regras de negócio em `domain/services/`, mensagens PT-BR via `errors.py`, schemas Pydantic `Create`/`Update` em `domain/schemas.py`, migração Alembic (autogenerate + seeds versionados) aplicada nos dois bancos, auditoria imutável com mascaramento via `domain/audit.py` em todos os CRUD. Catálogos (`bgp_policy_profiles`, `communities`) nascem **read-only** (só leitura; CRUD de catálogo não existe no ciclo A — §9 expõe apenas GET list) e ficam **fora** do TRUNCATE do conftest: são seedados pela migration e imutáveis neste plano.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic, PostgreSQL (compose dev), Pydantic v2, pytest com banco real truncado por teste, `uv` para comandos.

**Spec:** [docs/superpowers/specs/2026-09-02-gerenet-ciclo-a-sot-downstreams-design.md](../specs/2026-09-02-gerenet-ciclo-a-sot-downstreams-design.md) — o plano argumenta a partir da spec; o executor lê ambas. O ciclo A foi fatiado em 3 planos: Plano 1 (núcleo + IPAM + auditoria — **concluído**), **este** (sessões BGP, prefixos autorizados, produtos, communities), Plano 3 (API REST nova + CLI nova). A API/CLI **não** entram neste plano; aqui nascem modelos, migração com seeds e os serviços que o P3 vai expor.

## Global Constraints

- Idioma dos artefatos: **PT-BR**; código (identificadores, nomes de tabelas/colunas, valores de enum) em **inglês** — padrão F1/P1.
- Mensagens de erro de domínio em PT-BR via exceções de `gerenet.domain.services.errors`.
- **Nunca** credencial/segredo em banco, YAML, Git, logs, snapshots ou auditoria — só Vault. A coluna `password_ref` (path Vault) existe; **nenhum caminho de código a preenche neste plano** (password set = Plano 3 §8) e os schemas não a expõem.
- Soft-delete via `admin_status` em todas as entidades novas; desativar nunca exclui (§14.1). Associação N:N `bgp_session_communities` é o único objeto sem soft-delete: a linha é removida fisicamente e a trilha fica na auditoria (ruling 13).
- **Antes de ler código-fonte, rodar `graphify query "<assunto>"`** — regra do repositório (vale para subagentes).
- Rodar a suíte com o compose dev de pé (`docker compose up -d`): postgres com `gerenet` e `gerenet_test` migrados até `d8458305ab7e` (head atual do P1). Suíte completa com `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q` (nunca matar o worker dev do Redis db 0).
- TDD: teste falha → implementação mínima → teste passa → **commit por task** com `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
- Comandos: `uv run pytest <arquivo> -v` (um arquivo), `uv run alembic upgrade head` (dev) e `GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head` (test).
- Cadeia de migrations atual: `4b9aa889400e` (initial) → `a8acda79738d` (ssh_port) → `4132192e9f3b` (sot_core) → `d8458305ab7e` (asn_bigint). A nova tem `down_revision="d8458305ab7e"`.
- Auditoria: helper `domain/audit.py`; `details = {"objeto", "objeto_id", "antes", "depois"}`; antes/depois com apenas os campos alterados; tipos novos `bgp_session.create|update|disable|add_community|remove_community` e `authorization.create|disable`.
- Enum `family` PG já existe (criado no P1, usado por `vlans.family`): `bgp_sessions.afi` e `bgp_prefix_authorizations.family` **reutilizam** o tipo (`sa.Enum('ipv4','ipv6', name='family')` na migration sem novo CREATE TYPE; no modelo, `Enum(*FAMILY, name="family")` — não declarar `create_type`).
- `tests/conftest.py` TRUNCATE por teste: **acrescenta** `bgp_sessions`, `bgp_session_communities`, `bgp_prefix_authorizations`; **não** trunca `bgp_policy_profiles` nem `communities` (seedadas pela migration — catálogo de referência; ver ruling 2).
- Regras de lint implícitas (sem runner): código no estilo do repo (aspas simples, type hints `Mapped[...]`, `Session` tipada, imports do `select`/`IntegrityError` como nos serviços do P1).
- Ledger do SDD (execução): `.superpowers/sdd/2026-09-02-gerenet-ciclo-a-plano-2-bgp/progress.md`.

## Decisões deste plano (rulings sobre a spec — registrar no ledger do SDD)

1. **Catálogo read-only no ciclo A**: `bgp_policy_profiles` e `communities` só têm `get`/`list` no serviço (o §9 do design expõe apenas `policy-profiles GET list`; CRUD de catálogo e a exposição de communities são decisão do P3/ciclo B). Sessões e autorizações referenciam perfis/communities por id; perfis de importação nascem no ciclo B (spec §4), mas a coluna `import_profile_id` e a regra de direção já valem desde já.
2. **Catálogo fora do TRUNCATE**: o conftest não trunca `bgp_policy_profiles`/`communities` — são seeds de migration (referência imutável neste plano); as 3 tabelas dinâmicas (`bgp_sessions`, `bgp_session_communities`, `bgp_prefix_authorizations`) entram no TRUNCATE. Testes nunca criam linhas de catálogo sem limpá-las (os roundtrips da Task 1 fazem `delete` explícito).
3. **Prefixo autorizado não tem UPDATE de conteúdo** (§9: "prefix-authorizations: GET · POST · PATCH disable"): mudar um prefixo = desativar o antigo + criar o novo (trilha completa; evita o furo da regra de sobreposição num update). Só `create`, `get`, `list` e `disable`.
4. **Sessões: dois guards de duplicidade, nessa ordem** — (a) outra sessão **ativa** com mesmo (device, VRF do circuito, afi), mensagem verbatim da spec §5: `Já existe sessão {afi} ativa no equipamento {device} (VRF {vrf}).` — com `VRF pública` quando o circuito não tem VRF; (b) outra sessão ativa com o mesmo par (local, remoto) comparado **como conjunto** (par trocado também colide: a mesma sessão vista do lado oposto; no SoT o local é sempre o nosso edge), mensagem `Já existe sessão ativa entre {local} e {remote}.`. A regra do par é **global** (spec: "nem com o mesmo par ativo"); a da linha é por device. Sem constraint UNIQUE no banco — regras de serviço, como a sobreposição de autorizações (spec §5).
5. **Endereços de sessão**: validados por `ipaddress` com a família do `afi` (e `source_address` quando presente); comparação de par canônica por `int(ipaddress)`, armazenamento como digitado.
6. **ASNs**: `asn_local` default `device.asn` (device sem ASN e campo omitido ⇒ erro); `asn_remote` default `organization.asn` quando existe; quando `organization.asn` existe, um valor explícito **deve** ser igual; organização sem ASN exige `asn_remote` explícito. Valores explícitos passam por `asn_valido` (mensagem `ASN inválido ou reservado: {n}.`). Sessão sempre nasce com os dois ASNs resolvidos (`asn_remote` NOT NULL no banco; `asn_local` nullable na tabela — spec §4 L110-111).
7. **Update de sessão = revalidação completa do estado mesclado** (padrão `update_circuit` do P1): muda `circuit_id`/`device_id`/`afi` e revalida tudo contra o novo estado, com duplicidade `ignorando a própria sessão`. Campos not-null (`circuit_id`, `device_id`, `afi`, `local_address`, `remote_address`, `asn_local`, `asn_remote`) rejeitam null explícito com `<campo> é obrigatório.`; campos nullable (`source_address`, `import_profile_id`, `export_profile_id`, `maximum_prefix`, `maximum_prefix_threshold`, `local_preference`, `med`, `prepend`, `keepalive`, `holdtime`, `description`) aceitam null explícito = limpar.
8. **`password_ref`** (coluna) existe com o comentário "path no Vault; valor nunca no banco", mas nenhum schema/caminho a preenche neste plano (Plano 3 §8: `password set` grava o valor no Vault e preenche só o path). `has_password` é derivado — exposição é do P3.
9. **Ranges só onde a spec explicita**: `maximum_prefix_threshold` 0–100 e `prepend` 0–10 via `Field(ge/le)` nos schemas; os demais ints (maximum_prefix, local_preference, med, keepalive, holdtime) livres — renderização do ciclo B valida.
10. **Vínculo do perfil**: `import_profile_id` só aceita perfil `direction=import`; `export_profile_id` só `direction=export` (mensagem `Perfil {name} tem direção {direction} e não pode ser o perfil de {importação|exportação} da sessão.`); id inexistente ⇒ `NotFoundError` (perfil é FK).
11. **Guards de estado**: sessão exige **circuito ativo** (`Circuito {code} desativado não recebe sessões.`); autorização exige **organização ativa** (`Organização {name} desativada não recebe autorizações.`). Nenhum check de `admin_status` do device (padrão do P1: circuitos não checam o device).
12. **Associações community↔sessão moram em `services/bgp_sessions.py`** (o agregado é a sessão): `add_community(session, session_id, community_id, *, actor)` e `remove_community(session, session_id, community_id, *, actor)`. Auditoria `bgp_session.add_community` (antes=None; depois={community_id, community}) e `bgp_session.remove_community` (antes={...}; depois=None). **Sem transição = no-op sem evento** (Ruling 5 do P1: só transições de fato auditam). Exposição em rota/CLI é decisão do P3.
13. **Deleção física da associação N:N** é permitida (não é objeto de negócio — não tem `admin_status`; a trilha fica nos eventos `bgp_session.add_community`/`remove_community`). Única exceção à regra de soft-delete, que continua valendo para as entidades.
14. **Enums novos**: `DIRECTION=("import","export")` (nome PG `direction`), `PROFILE_KIND=("produto",)` (nome PG `profile_kind` — extensível), `AUTH_ORIGIN=("manual",)` (nome PG `auth_origin`; IRR/RPKI = F5). `FAMILY` (nome PG `family`) é reaproveitado — nenhum CREATE TYPE novo para ele.

---

## Estrutura de arquivos

**Criar:**
- `alembic/versions/<rev>_bgp_sot.py` — autogenerate revisado + seeds dos catálogos (produtos §25.5 e communities §25.6)
- `src/gerenet/domain/services/policy_profiles.py` — `get_policy_profile`, `list_policy_profiles` (catálogo read-only)
- `src/gerenet/domain/services/communities.py` — `get_community`, `list_communities` (catálogo read-only)
- `src/gerenet/domain/services/prefix_authorizations.py` — `create_authorization`, `get_authorization`, `list_authorizations`, `disable_authorization`
- `src/gerenet/domain/services/bgp_sessions.py` — `create_session`, `get_session`, `list_sessions` (Task 4); `update_session`, `disable_session`, `add_community`, `remove_community` (Task 5)
- `tests/domain/test_bgp_models.py` — roundtrip das tabelas novas + seeds da migration
- `tests/domain/test_policy_profiles_service.py`, `test_communities_service.py` — catálogos
- `tests/domain/test_prefix_authorizations_service.py` — autorizações
- `tests/domain/test_bgp_sessions_service.py` — sessões (Task 4 cria; Task 5 estende)

**Modificar:**
- `src/gerenet/domain/models.py` — 3 tuplas de enum novas + 5 classes (`PolicyProfile`, `Community`, `BgpSession`, `BgpSessionCommunity`, `BgpPrefixAuthorization`)
- `src/gerenet/domain/schemas.py` — `PrefixAuthorizationCreate` (Task 3); `BgpSessionCreate` (Task 4); `BgpSessionUpdate` (Task 5)
- `tests/conftest.py` — lista do TRUNCATE

Sem mudanças em `audit.py`, `errors.py`, `validators.py` nem nos serviços do P1: o `cidr_valido(cidr, familia)` existente já valida CIDR alinhado **e** a família (reuso na autorização); `asn_valido` retorna bool e o chamador levanta a mensagem PT (padrão P1).

---

### Task 1: Modelos BGP + migração `bgp_sot` com seeds + conftest

**Files:**
- Modify: `src/gerenet/domain/models.py` (tuplas de enum no topo; classes no fim)
- Create: `alembic/versions/<rev>_bgp_sot.py` (autogenerate + edição manual com seeds)
- Modify: `tests/conftest.py` (lista do TRUNCATE)
- Create: `tests/domain/test_bgp_models.py`

**Interfaces:**
- Produces: classes `PolicyProfile`, `Community`, `BgpSession`, `BgpSessionCommunity`, `BgpPrefixAuthorization` com as colunas exatas da spec §4 (abaixo) e enums de módulo: `DIRECTION=("import","export")`, `PROFILE_KIND=("produto",)`, `AUTH_ORIGIN=("manual",)` — nomes PG `direction`, `profile_kind`, `auth_origin`; `FAMILY` já existe e é reusado por `bgp_sessions.afi` e `bgp_prefix_authorizations.family` (nome PG `family`). Seeds (migration de dados): 6 `bgp_policy_profiles` de exportação (§25.5) e 3 `communities` (§25.6). As tasks 2–5 consomem estes nomes verbatim e as seeds pelo nome (`list_policy_profiles`/`list_communities` resolvem ids nos testes).

- [ ] **Step 1: Adicionar as tuplas de enum ao topo do `models.py`**

No topo de `src/gerenet/domain/models.py`, após `PREFIX_KIND = ("p2p",)` (linha 30), acrescente:

```python
DIRECTION = ("import", "export")
PROFILE_KIND = ("produto",)
AUTH_ORIGIN = ("manual",)
```

Não toque em `FAMILY` — ele já está lá (linha 28) e será reaproveitado.

- [ ] **Step 2: Escrever os testes que falham — `tests/domain/test_bgp_models.py`**

Crie o arquivo (estilo dos testes do P1; o ambiente usa os serviços do P1 para montar FKs):

```python
"""Roundtrip das tabelas BGP e presença dos seeds das migrations (Tasks 1–2)."""
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


def _limpa_catalogo(db_session: Session) -> None:
    """Os catálogos não são truncados por teste (seeds de migration); este teste
    insere linhas próprias e as remove ao fim para não poluir os demais."""
    db_session.execute(
        text(
            "delete from bgp_policy_profiles where name like 'rt-%'; "
            "delete from communities where name like 'rt-%';"
        )
    )
    db_session.commit()


def _ambiente(db_session: Session) -> dict:
    """Org (ASN 64512), site e um NE8000 (ASN 64600) vinculado + circuito."""
    site = create_site(db_session, SiteCreate(name="pop-rt-01"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente RT", asn=64512), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne8k-rt", management_address="10.9.0.1", asn=64600),
        actor="cli",
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-rt", management_address="10.9.0.2"), actor="cli"
    )
    link_device(db_session, site.id, ne.id, actor="cli")
    link_device(db_session, site.id, sw.id, actor="cli")
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-RT", organization_id=org.id, site_id=site.id,
            access_device_id=sw.id, access_port="GE0/0/1", edge_device_id=ne.id,
        ),
        actor="cli",
    )
    return {"org_id": org.id, "site_id": site.id, "ne_id": ne.id, "circuit_id": circ.id}


def test_roundtrip_perfil_e_community(db_session: Session) -> None:
    _limpa_catalogo(db_session)
    try:
        perfil = models.PolicyProfile(
            name="rt-full", label="Roundtrip", direction="export", kind="produto"
        )
        com = models.Community(name="rt-blackhole", notes="roundtrip")
        db_session.add_all([perfil, com])
        db_session.commit()
        assert perfil.id and com.id

        relido = db_session.get(models.PolicyProfile, perfil.id)
        assert (relido.name, relido.direction, relido.kind) == ("rt-full", "export", "produto")
        assert relido.prefixes is None
        assert db_session.get(models.Community, com.id).name == "rt-blackhole"
    finally:
        _limpa_catalogo(db_session)


def test_seeds_dos_catalogos_presentes(db_session: Session) -> None:
    """Produtos §25.5 (exportação) e communities §25.6, inseridos pela migration."""
    nomes = set(db_session.scalars(select(models.PolicyProfile.name)).all())
    assert nomes == {"default", "default_internas", "parcial", "full", "cdn", "personalizado"}
    rotulos = dict(
        db_session.execute(
            select(models.PolicyProfile.name, models.PolicyProfile.label)
        ).all()
    )
    assert rotulos["default"] == "Somente default"
    assert rotulos["default_internas"] == "Default + internas"
    assert rotulos["parcial"] == "Tabela parcial"
    assert rotulos["full"] == "Full routing"
    assert rotulos["cdn"] == "CDN"
    assert rotulos["personalizado"] == "Personalizado"
    assert all(d == "export" for d in db_session.scalars(
        select(models.PolicyProfile.direction)
    ).all())
    assert all(k == "produto" for k in db_session.scalars(
        select(models.PolicyProfile.kind)
    ).all())

    coms = set(db_session.scalars(select(models.Community.name)).all())
    assert coms == {"blackhole", "no-export", "no-advertise"}


def test_roundtrip_autorizacao(db_session: Session) -> None:
    org_id = _ambiente(db_session)["org_id"]
    auth = models.BgpPrefixAuthorization(
        organization_id=org_id, family="ipv4", prefix="200.160.0.0/22", origin="manual"
    )
    db_session.add(auth)
    db_session.commit()

    relida = db_session.get(models.BgpPrefixAuthorization, auth.id)
    assert (relida.family, relida.prefix, relida.origin) == ("ipv4", "200.160.0.0/22", "manual")


def test_roundtrip_sessao_e_associacao(db_session: Session) -> None:
    env = _ambiente(db_session)
    sessao = models.BgpSession(
        circuit_id=env["circuit_id"], device_id=env["ne_id"], afi="ipv4",
        local_address="100.64.0.1", remote_address="100.64.0.2",
        asn_local=64600, asn_remote=64512,
    )
    db_session.add(sessao)
    db_session.commit()

    relida = db_session.get(models.BgpSession, sessao.id)
    assert relida.afi == "ipv4"
    assert relida.asn_local == 64600
    assert relida.bfd_enabled is False  # defaults do modelo

    com = db_session.scalars(
        select(models.Community).where(models.Community.name == "no-export")
    ).first()
    vinculo = models.BgpSessionCommunity(session_id=sessao.id, community_id=com.id)
    db_session.add(vinculo)
    db_session.commit()
    assert vinculo.id
```

Os testes usam serviços do P1 e o fixture `db_session` do conftest — não altere o conftest ainda neste passo.

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_bgp_models.py -v`
Expected: FAIL — `models.PolicyProfile` inexistente (ImportError).

- [ ] **Step 4: Implementar os modelos — adicionar as classes ao fim do `models.py`**

No **fim** de `src/gerenet/domain/models.py` (após `IpPrefix`), adicione as 5 classes — estilo idêntico ao do P1 (timestamps com `server_default=func.now()`, `onupdate=func.now()`; enums como tupla + `Enum(*..., name=...)`; `BigInteger` para ASNs de 32 bits — mesmo motivo do `d8458305ab7e`):

```python
class PolicyProfile(Base):
    """Produto de roteamento reutilizável (§6.5/§25.5) — catálogo read-only no ciclo A.

    direction import nasce no ciclo B junto da renderização; os seeds deste
    plano são os 6 produtos de exportação do §25.5.
    """

    __tablename__ = "bgp_policy_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # slug EN
    label: Mapped[str] = mapped_column(String(64), nullable=False)  # PT-BR
    direction: Mapped[str] = mapped_column(Enum(*DIRECTION, name="direction"), nullable=False)
    kind: Mapped[str] = mapped_column(
        Enum(*PROFILE_KIND, name="profile_kind"), default="produto", nullable=False
    )
    prefixes: Mapped[list | None] = mapped_column(JSON)  # CIDRs de cdn/personalizado
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Community(Base):
    """Community BGP reutilizável (§25.6) — catálogo read-only no ciclo A.

    O valor concreto (ex.: NO_EXPORT vs ASN:tag) é definido na renderização do
    ciclo B conforme o template e o ASN local; aqui só o nome lógico.
    """

    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BgpSession(Base):
    """Sessão BGP por família (§6.3) — SoT da intenção; sem renderização (ciclo B)."""

    __tablename__ = "bgp_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_id: Mapped[int] = mapped_column(ForeignKey("circuits.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    afi: Mapped[str] = mapped_column(Enum(*FAMILY, name="family"), nullable=False)
    local_address: Mapped[str] = mapped_column(String(64), nullable=False)
    remote_address: Mapped[str] = mapped_column(String(64), nullable=False)
    source_address: Mapped[str | None] = mapped_column(String(64))
    asn_local: Mapped[int | None] = mapped_column(BigInteger)  # default device.asn (§4); sempre resolvido no serviço
    asn_remote: Mapped[int] = mapped_column(BigInteger, nullable=False)  # default organization.asn (§4)
    description: Mapped[str | None] = mapped_column(String(255))
    import_profile_id: Mapped[int | None] = mapped_column(ForeignKey("bgp_policy_profiles.id"))
    export_profile_id: Mapped[int | None] = mapped_column(ForeignKey("bgp_policy_profiles.id"))
    maximum_prefix: Mapped[int | None] = mapped_column(Integer)
    maximum_prefix_threshold: Mapped[int | None] = mapped_column(Integer)  # 0-100 (%)
    local_preference: Mapped[int | None] = mapped_column(Integer)
    med: Mapped[int | None] = mapped_column(Integer)
    prepend: Mapped[int | None] = mapped_column(Integer)  # 0-10
    keepalive: Mapped[int | None] = mapped_column(Integer)
    holdtime: Mapped[int | None] = mapped_column(Integer)
    bfd_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    graceful_restart: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    shutdown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_default_route: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    password_ref: Mapped[str | None] = mapped_column(String(255))  # path Vault; valor nunca no banco
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BgpSessionCommunity(Base):
    """Associação N:N sessão ↔ community (UNIQUE por par). Linha deletável — a
    trilha fica na auditoria (ruling 13); sem soft-delete."""

    __tablename__ = "bgp_session_communities"

    __table_args__ = (
        UniqueConstraint("session_id", "community_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("bgp_sessions.id"), nullable=False)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BgpPrefixAuthorization(Base):
    """Prefixo autorizado de um downstream (origem manual; IRR/RPKI = F5)."""

    __tablename__ = "bgp_prefix_authorizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    family: Mapped[str] = mapped_column(Enum(*FAMILY, name="family"), nullable=False)
    prefix: Mapped[str] = mapped_column(String(64), nullable=False)  # CIDR alinhado
    origin: Mapped[str] = mapped_column(
        Enum(*AUTH_ORIGIN, name="auth_origin"), default="manual", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

Nota: os enums `direction`, `profile_kind`, `auth_origin` são criados implicitamente pelo PG na primeira tabela que os usa; `family` já existe do P1 — o modelo não declara `create_type` (comportamento default de comparação/uso por nome).

- [ ] **Step 5: Gerar e revisar a migration `bgp_sot`**

Gere o autogenerate (contra o banco dev, migrado até o head do P1):

```bash
uv run alembic revision --autogenerate -m "bgp_sot"
```

Abra o arquivo gerado `alembic/versions/<rev>_bgp_sot.py` e confira, **editando o que precisar**:

1. `down_revision` = `'d8458305ab7e'` (o head atual — conferir com `uv run alembic heads`).
2. `upgrade()` cria exatamente as 5 tabelas novas nesta ordem (sem drops/alters de outras tabelas): `bgp_policy_profiles` → `communities` → `bgp_sessions` → `bgp_session_communities` → `bgp_prefix_authorizations`.
3. Colunas nullable corretas: `bgp_sessions.asn_remote` **NOT NULL** e `asn_local` nullable (spec §4 L110-111 — o serviço resolve ambos na criação; a garantia do banco fica no `asn_remote`); `BgpSessionCommunity` sem `updated_at` e com `created_at` só.
4. `bgp_sessions.afi` e `bgp_prefix_authorizations.family` aparecem como `sa.Enum('ipv4', 'ipv6', name='family')` — reuso do tipo existente, sem `create_type` (se o autogenerate emitir algo como `postgresql.ENUM(..., name='family', create_type=False)`, está correto; se tentar criar de novo, ajuste para apenas `name='family'` como nas colunas do P1 — conferir a migration `4132192e9f3b_sot_core.py` linha ~105).
5. As `UniqueConstraint` de `communities.name`, `bgp_policy_profiles.name` e `bgp_session_communities(session_id, community_id)` estão presentes.

- [ ] **Step 6: Adicionar os seeds ao fim do `upgrade()`**

No fim da função `upgrade()` do arquivo da migration, acrescente (estilo do data move do P1 — `bind.execute` com texto SQL):

```python
    # Seeds dos catálogos (§25.5/§25.6): 6 produtos de exportação + 3 communities.
    # on conflict do nothing torna o upgrade reexecutável (idempotência §3.2).
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "insert into bgp_policy_profiles (name, label, direction, kind, admin_status) "
            "values (:name, :label, 'export', 'produto', true) on conflict do nothing"
        ),
        [
            {"name": "default", "label": "Somente default"},
            {"name": "default_internas", "label": "Default + internas"},
            {"name": "parcial", "label": "Tabela parcial"},
            {"name": "full", "label": "Full routing"},
            {"name": "cdn", "label": "CDN"},
            {"name": "personalizado", "label": "Personalizado"},
        ],
    )
    bind.execute(
        sa.text(
            "insert into communities (name, admin_status) values (:name, true) "
            "on conflict do nothing"
        ),
        [{"name": nome} for nome in ("blackhole", "no-export", "no-advertise")],
    )
```

`prefixes` fica NULL nos seeds: os CIDRs concretos de `cdn`/`personalizado` são dado de operação (ciclo B/§8), não da migration (decisão registrada no design: "o tag de produto e os valores concretos são definidos na renderização do ciclo B").

- [ ] **Step 7: Atualizar o TRUNCATE do conftest**

Em `tests/conftest.py`, substitua a linha do `text("TRUNCATE ...")` por (mantendo o comentário explicativo acima da fixture):

```python
    # Catálogos (bgp_policy_profiles, communities) ficam de fora de propósito:
    # são seedados pela migration e imutáveis no ciclo A (ruling 2 do Plano 2).
    db_session.execute(
        text(
            "TRUNCATE audit_events, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups, bgp_sessions, bgp_session_communities, bgp_prefix_authorizations RESTART IDENTITY CASCADE"
        )
    )
```

- [ ] **Step 8: Aplicar a migration nos dois bancos**

```bash
uv run alembic upgrade head
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head
```

- [ ] **Step 9: Rodar os testes e ver passar**

Run: `uv run pytest tests/domain/test_bgp_models.py -v`
Expected: PASS (4 testes). Rode também a suíte inteira para garantir que nada do P1 quebrou (o TRUNCATE mudou): `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q` — deve seguir verde (97 do P1 + os novos).

- [ ] **Step 10: Commit**

```bash
git add src/gerenet/domain/models.py alembic/versions/<rev>_bgp_sot.py tests/conftest.py tests/domain/test_bgp_models.py
git commit -m "feat(SoT): tabelas BGP (sessões, autorizações, catálogos seedados) + migração bgp_sot

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Catálogos read-only — `policy_profiles` e `communities`

**Files:**
- Create: `src/gerenet/domain/services/policy_profiles.py`, `src/gerenet/domain/services/communities.py`
- Test: `tests/domain/test_policy_profiles_service.py`, `tests/domain/test_communities_service.py`

**Interfaces:**
- Consumes: modelos da Task 1 (classes `PolicyProfile`, `Community`); seeds da migration (Task 1).
- Produces:
  - `get_policy_profile(session, profile_id) -> models.PolicyProfile` (NotFoundError `Perfil {id} não encontrado.`), `list_policy_profiles(session, direction: str | None = None, include_disabled: bool = False) -> list[models.PolicyProfile]` — order by `name`; sem filtro de admin quando `include_disabled`.
  - `get_community(session, community_id) -> models.Community` (NotFoundError `Community {id} não encontrada.`), `list_communities(session, include_disabled: bool = False) -> list[models.Community]` — order by `name`.
  - As Tasks 4/5 consomem `get_policy_profile` (validação de direção) e `get_community`.

- [ ] **Step 1: Escrever os testes que falham**

`tests/domain/test_policy_profiles_service.py`:

```python
import pytest
from sqlalchemy.orm import Session

from gerenet.domain.services.errors import NotFoundError
from gerenet.domain.services.policy_profiles import (
    get_policy_profile,
    list_policy_profiles,
)


def test_catalogo_export_tem_os_seis_produtos(db_session: Session) -> None:
    nomes = [p.name for p in list_policy_profiles(db_session)]
    assert nomes == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
    ]  # order by name


def test_lista_filtra_direction(db_session: Session) -> None:
    assert len(list_policy_profiles(db_session, direction="export")) == 6
    assert list_policy_profiles(db_session, direction="import") == []


def test_get_policy_profile_por_id(db_session: Session) -> None:
    perfil = list_policy_profiles(db_session, direction="export")[0]
    assert get_policy_profile(db_session, perfil.id).id == perfil.id


def test_policy_profile_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Perfil 9999 não encontrado"):
        get_policy_profile(db_session, 9999)
```

`tests/domain/test_communities_service.py`:

```python
import pytest
from sqlalchemy.orm import Session

from gerenet.domain.services.communities import get_community, list_communities
from gerenet.domain.services.errors import NotFoundError


def test_catalogo_communities_tem_as_tres_sementes(db_session: Session) -> None:
    nomes = [c.name for c in list_communities(db_session)]
    assert nomes == ["blackhole", "no-advertise", "no-export"]  # order by name


def test_get_community_por_id(db_session: Session) -> None:
    com = list_communities(db_session)[0]
    assert get_community(db_session, com.id).id == com.id


def test_community_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Community 9999 não encontrada"):
        get_community(db_session, 9999)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_policy_profiles_service.py tests/domain/test_communities_service.py -v`
Expected: FAIL — módulo `services.policy_profiles`/`services.communities` inexistente.

- [ ] **Step 3: Implementar**

`src/gerenet/domain/services/policy_profiles.py`:

```python
"""Catálogo de produtos de roteamento (§6.5/§25.5) — somente leitura no ciclo A."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.services.errors import NotFoundError


def get_policy_profile(session: Session, profile_id: int) -> models.PolicyProfile:
    perfil = session.get(models.PolicyProfile, profile_id)
    if perfil is None:
        raise NotFoundError(f"Perfil {profile_id} não encontrado.")
    return perfil


def list_policy_profiles(
    session: Session, direction: str | None = None, include_disabled: bool = False
) -> list[models.PolicyProfile]:
    """Catálogo completo de exportação (importações nascem no ciclo B)."""
    stmt = select(models.PolicyProfile).order_by(models.PolicyProfile.name)
    if not include_disabled:
        stmt = stmt.where(models.PolicyProfile.admin_status.is_(True))
    if direction:
        stmt = stmt.where(models.PolicyProfile.direction == direction)
    return list(session.scalars(stmt))
```

`src/gerenet/domain/services/communities.py`:

```python
"""Catálogo de communities (§25.6) — somente leitura no ciclo A."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.services.errors import NotFoundError


def get_community(session: Session, community_id: int) -> models.Community:
    com = session.get(models.Community, community_id)
    if com is None:
        raise NotFoundError(f"Community {community_id} não encontrada.")
    return com


def list_communities(
    session: Session, include_disabled: bool = False
) -> list[models.Community]:
    stmt = select(models.Community).order_by(models.Community.name)
    if not include_disabled:
        stmt = stmt.where(models.Community.admin_status.is_(True))
    return list(session.scalars(stmt))
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `uv run pytest tests/domain/test_policy_profiles_service.py tests/domain/test_communities_service.py -v`
Expected: PASS (4 + 3 testes). Importante: as seeds vêm da migration aplicada na Task 1 — se os testes falharem com tabela vazia, confira o upgrade do banco de teste.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/domain/services/policy_profiles.py src/gerenet/domain/services/communities.py tests/domain/test_policy_profiles_service.py tests/domain/test_communities_service.py
git commit -m "feat(SoT): catálogos read-only de produtos de roteamento e communities

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Autorizações de prefixo (`prefix_authorizations`)

**Files:**
- Create: `src/gerenet/domain/services/prefix_authorizations.py`
- Modify: `src/gerenet/domain/schemas.py` (schema `PrefixAuthorizationCreate`)
- Test: `tests/domain/test_prefix_authorizations_service.py`

**Interfaces:**
- Consumes: modelos da Task 1; `get_organization` (organizations, P1); `cidr_valido(cidr, familia)` (validators, P1 — valida CIDR alinhado **e** família); `registrar` (audit).
- Produces: `create_authorization(session, data: PrefixAuthorizationCreate, *, actor)`, `get_authorization(session, authorization_id)`, `list_authorizations(session, organization_id: int | None = None, family: str | None = None, include_disabled: bool = False)`, `disable_authorization(session, authorization_id, *, actor)` — auditoria `authorization.create|disable`. Regra (spec §4/§5): nenhum prefixo **ativo** sobrepõe autorização de **organização distinta** (a mesma organização pode sobrepor a si mesma — listas contíguas/sobrepostas); mensagem verbatim `Prefixo {p} sobrepõe autorização de {org}.` Sem UPDATE de conteúdo (ruling 3).

- [ ] **Step 1: Escrever os testes que falham — `tests/domain/test_prefix_authorizations_service.py`**

```python
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import OrganizationCreate, PrefixAuthorizationCreate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import (
    create_authorization,
    disable_authorization,
    get_authorization,
    list_authorizations,
)


def _org(db_session: Session, nome: str, asn: int) -> int:
    return create_organization(db_session, OrganizationCreate(name=nome, asn=asn), actor="cli").id


def _ultimo_evento(db_session: Session) -> models.AuditEvent:
    eventos = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()
    assert eventos, "nenhum evento de auditoria"
    return eventos[0]


def test_cria_lista_filtra_e_desativa(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Alfa", 64512)
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.160.0.0/22"
        ),
        actor="cli",
    )
    assert auth.origin == "manual"
    assert [a.prefix for a in list_authorizations(db_session, organization_id=org_id)] == [
        "200.160.0.0/22"
    ]
    assert list_authorizations(db_session, family="ipv6", organization_id=org_id) == []

    disable_authorization(db_session, auth.id, actor="cli")
    assert list_authorizations(db_session, organization_id=org_id) == []
    assert [
        a.prefix
        for a in list_authorizations(db_session, organization_id=org_id, include_disabled=True)
    ] == ["200.160.0.0/22"]


def test_mesma_organizacao_pode_sobrepor(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Beta", 64513)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.160.0.0/22"
        ),
        actor="cli",
    )
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.160.0.0/24"
        ),
        actor="cli",
    )
    assert auth.prefix == "200.160.0.0/24"


def test_sobreposicao_entre_organizacoes_vira_conflito(db_session: Session) -> None:
    org_a = _org(db_session, "Cliente Gama", 64514)
    org_b = _org(db_session, "Cliente Delta", 64515)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_a, family="ipv4", prefix="200.160.0.0/22"
        ),
        actor="cli",
    )
    # mais específico dentro do bloco do outro → sobrepõe
    with pytest.raises(ConflictError, match="sobrepõe autorização de Cliente Gama"):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_b, family="ipv4", prefix="200.160.0.0/24"
            ),
            actor="cli",
        )
    # contíguo não sobrepõe
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_b, family="ipv4", prefix="200.160.4.0/22"
        ),
        actor="cli",
    )


def test_autorizacao_desativada_nao_bloqueia_outra_organizacao(db_session: Session) -> None:
    org_a = _org(db_session, "Cliente Épsilon", 64516)
    org_b = _org(db_session, "Cliente Zeta", 64517)
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_a, family="ipv4", prefix="200.161.0.0/22"
        ),
        actor="cli",
    )
    disable_authorization(db_session, auth.id, actor="cli")
    nova = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_b, family="ipv4", prefix="200.161.0.0/24"
        ),
        actor="cli",
    )
    assert nova.prefix == "200.161.0.0/24"


def test_familias_diferentes_nao_conflitam(db_session: Session) -> None:
    org_a = _org(db_session, "Cliente Eta", 64518)
    org_b = _org(db_session, "Cliente Teta", 64519)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_a, family="ipv6", prefix="2804:194C::/32"
        ),
        actor="cli",
    )
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_b, family="ipv4", prefix="200.162.0.0/22"
        ),
        actor="cli",
    )  # sem conflito


def test_cidr_desalinhado_ou_de_outra_familia_rejeitado(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Iota", 64520)
    with pytest.raises(ValidationError, match="não está alinhado"):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_id, family="ipv4", prefix="200.160.0.1/22"
            ),
            actor="cli",
        )
    with pytest.raises(ValidationError, match="não é um prefixo IPv6"):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_id, family="ipv6", prefix="200.160.0.0/22"
            ),
            actor="cli",
        )


def test_organizacao_desativada_nao_recebe_autorizacao(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Kappa", 64521)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.163.0.0/22"
        ),
        actor="cli",
    )
    # desativa a organização pelo serviço do P1 (o helper só cria)
    from gerenet.domain.services.organizations import disable_organization

    disable_organization(db_session, org_id, actor="cli")
    with pytest.raises(ConflictError, match="desativada não recebe autorizações"):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_id, family="ipv4", prefix="200.164.0.0/22"
            ),
            actor="cli",
        )


def test_audita_criacao_e_desativacao(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Lambda", 64522)
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.165.0.0/22", notes="bloco do cliente"
        ),
        actor="cli",
    )
    evento = _ultimo_evento(db_session)
    assert evento.type == "authorization.create"
    assert evento.details["objeto_id"] == auth.id
    assert evento.details["depois"]["prefix"] == "200.165.0.0/22"

    disable_authorization(db_session, auth.id, actor="cli")
    evento = _ultimo_evento(db_session)
    assert evento.type == "authorization.disable"
    assert evento.details["antes"] == {"admin_status": True}
    assert evento.details["depois"] == {"admin_status": False}

    # disable repetido é no-op sem novo evento
    disable_authorization(db_session, auth.id, actor="cli")
    desativacoes = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "authorization.disable")
    ).all()
    assert len(desativacoes) == 1


def test_get_e_autorizacao_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Autorização 9999 não encontrada"):
        get_authorization(db_session, 9999)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_prefix_authorizations_service.py -v`
Expected: FAIL — módulo `services.prefix_authorizations` inexistente (e schema `PrefixAuthorizationCreate`).

- [ ] **Step 3: Escrever o schema — acrescente ao fim de `src/gerenet/domain/schemas.py`**

```python
class PrefixAuthorizationCreate(BaseModel):
    organization_id: int
    family: Literal["ipv4", "ipv6"]
    prefix: str = Field(min_length=1, max_length=64)
    notes: str | None = None
```

(`Literal` já está importado no arquivo desde o P1 — não duplique o import.)

- [ ] **Step 4: Implementar — crie `src/gerenet/domain/services/prefix_authorizations.py`**

```python
"""Autorizações de prefixo de downstreams (§6.4) — origem manual neste ciclo."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import PrefixAuthorizationCreate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.validators import cidr_valido


def _organizacao_conflitante(
    session: Session, *, organization_id: int, family: str, prefix: str
) -> models.Organization | None:
    """Outra organização com autorização ATIVA que sobrepõe o prefixo (spec §4).

    A mesma organização pode listar blocos contíguos/sobrepostos; famílias
    diferentes nunca se comparam (versões distintas de ipaddress).
    """
    rede = cidr_valido(prefix, family)
    stmt = select(models.BgpPrefixAuthorization).where(
        models.BgpPrefixAuthorization.admin_status.is_(True),
        models.BgpPrefixAuthorization.family == family,
    )
    for linha in session.scalars(stmt):
        if linha.organization_id == organization_id:
            continue
        if rede.overlaps(cidr_valido(linha.prefix, family)):
            org = session.get(models.Organization, linha.organization_id)
            return org
    return None


def create_authorization(
    session: Session, data: PrefixAuthorizationCreate, *, actor: str
) -> models.BgpPrefixAuthorization:
    org = get_organization(session, data.organization_id)
    if org.admin_status is False:
        raise ConflictError(f"Organização {org.name} desativada não recebe autorizações.")
    cidr_valido(data.prefix, data.family)  # CIDR alinhado da família certa (mensagens PT)
    outra = _organizacao_conflitante(
        session, organization_id=data.organization_id, family=data.family, prefix=data.prefix
    )
    if outra is not None:
        raise ConflictError(f"Prefixo {data.prefix} sobrepõe autorização de {outra.name}.")
    dump = data.model_dump()
    auth = models.BgpPrefixAuthorization(**dump)
    session.add(auth)
    try:
        session.flush()  # valida a FK antes da auditoria
        registrar(
            session, tipo="authorization.create", ator=actor, objeto="authorization",
            objeto_id=auth.id, antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "Não foi possível criar a autorização de prefixo: conflito de integridade."
        ) from exc
    session.refresh(auth)
    return auth


def get_authorization(
    session: Session, authorization_id: int
) -> models.BgpPrefixAuthorization:
    auth = session.get(models.BgpPrefixAuthorization, authorization_id)
    if auth is None:
        raise NotFoundError(f"Autorização {authorization_id} não encontrada.")
    return auth


def list_authorizations(
    session: Session,
    organization_id: int | None = None,
    family: str | None = None,
    include_disabled: bool = False,
) -> list[models.BgpPrefixAuthorization]:
    stmt = select(models.BgpPrefixAuthorization).order_by(
        models.BgpPrefixAuthorization.family, models.BgpPrefixAuthorization.prefix
    )
    if not include_disabled:
        stmt = stmt.where(models.BgpPrefixAuthorization.admin_status.is_(True))
    if organization_id is not None:
        stmt = stmt.where(models.BgpPrefixAuthorization.organization_id == organization_id)
    if family is not None:
        stmt = stmt.where(models.BgpPrefixAuthorization.family == family)
    return list(session.scalars(stmt))


def disable_authorization(
    session: Session, authorization_id: int, *, actor: str
) -> models.BgpPrefixAuthorization:
    """Desativa (sem excluir — §14.1). Mudar um prefixo = desativar + criar (ruling 3)."""
    auth = get_authorization(session, authorization_id)
    if auth.admin_status is False:
        return auth
    auth.admin_status = False
    registrar(
        session, tipo="authorization.disable", ator=actor, objeto="authorization",
        objeto_id=auth.id, antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return auth
```

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `uv run pytest tests/domain/test_prefix_authorizations_service.py -v`
Expected: PASS (9 testes). Se o teste `test_audita_criacao_e_desativacao` falhar na asserção de "disable repetido não gera novo evento", confira a asserção `_ultimo_evento(...).type` — ela é feita após o 2º disable e deve continuar `authorization.disable` (o 2º disable é no-op sem evento; se houver um evento a mais, o serviço está auditando sem transição — corrija no serviço, não no teste).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/prefix_authorizations.py tests/domain/test_prefix_authorizations_service.py
git commit -m "feat(SoT): autorizações de prefixo por organização (origem manual, sem sobreposição entre organizações)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Sessões BGP — criação, leitura e listagem (`bgp_sessions`)

**Files:**
- Create: `src/gerenet/domain/services/bgp_sessions.py`
- Modify: `src/gerenet/domain/schemas.py` (schema `BgpSessionCreate`)
- Test: `tests/domain/test_bgp_sessions_service.py` (a Task 5 acrescenta funções ao mesmo arquivo)

**Interfaces:**
- Consumes: modelos da Task 1 (`BgpSession`); `get_circuit`/`create_circuit` (circuits P1), `get_device`/`create_device` (devices F1), `get_organization`/`create_organization` (organizations P1), `get_site`/`create_site`/`link_device` (sites P1), `get_policy_profile` (Task 2), `get_community` (Task 2 — Task 5), `asn_valido` (validators P1), `registrar` (audit).
- Produces (nomes verbatim p/ a Task 5 e o P3): `create_session(session, data: BgpSessionCreate, *, actor) -> models.BgpSession`, `get_session(session, session_id) -> models.BgpSession`, `list_sessions(session, circuit_id: int | None = None, device_id: int | None = None, include_disabled: bool = False) -> list[models.BgpSession]` (order by `id`). Helpers privados usados também pela Task 5: `_valida_endereco`, `_valida_asn`, `_valida_perfil`, `_colidente_linha`, `_colidente_par`, `_vrf_texto`. Auditoria `bgp_session.create` (antes=None; depois = dump resolvido). Regras da spec §4 na criação: `device_id` ∈ {edge, backup_edge} do circuito; endereços com a família do `afi` (source_address idem, quando presente); defaults de ASN (ruling 6); perfis com a direção certa (ruling 10); duplicidades (ruling 4).

- [ ] **Step 1: Escrever os testes que falham — `tests/domain/test_bgp_sessions_service.py`**

```python
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services.bgp_sessions import (
    create_session,
    get_session,
    list_sessions,
)
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session) -> dict:
    """Org (ASN 64512), site, switch e 2 NE8000 (ASNs 64600/64601) no site."""
    site = create_site(db_session, SiteCreate(name="pop-bgp-01"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente BGP", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-bgp", management_address="10.8.0.2"), actor="cli")
    ne1 = create_device(
        db_session, DeviceCreate(name="ne8k-bgp1", management_address="10.8.0.1", asn=64600),
        actor="cli",
    )
    ne2 = create_device(
        db_session, DeviceCreate(name="ne8k-bgp2", management_address="10.8.0.3", asn=64601),
        actor="cli",
    )
    for dev in (sw, ne1, ne2):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne1_id": ne1.id, "ne2_id": ne2.id}


def _circuito(db_session: Session, env: dict, *, code: str, edge_id: int, vrf: str | None = None) -> int:
    """Circuito no ambiente padrão; devolve o id."""
    return create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1", edge_device_id=edge_id,
            vrf=vrf,
        ),
        actor="cli",
    ).id


def _sessao_data(
    env: dict, circuit_id: int, edge_id: int, *, afi: str = "ipv4",
    local: str = "100.64.0.1", remote: str = "100.64.0.2", **extra,
) -> BgpSessionCreate:
    base = dict(
        circuit_id=circuit_id, device_id=edge_id, afi=afi,
        local_address=local, remote_address=remote,
    )
    base.update(extra)
    return BgpSessionCreate(**base)


def test_cria_sessao_com_defaults_de_asn(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0001", edge_id=env["ne1_id"])
    sessao = create_session(
        db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli"
    )
    # defaults: asn_local = device.asn (64600); asn_remote = organization.asn (64512)
    assert sessao.asn_local == 64600
    assert sessao.asn_remote == 64512
    assert sessao.bfd_enabled is False
    assert [s.id for s in list_sessions(db_session)] == [sessao.id]


def test_cria_com_overrides_e_filtros_de_lista(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0002", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    circ2 = _circuito(db_session, env, code="CIRC-0003", edge_id=env["ne2_id"], vrf="CLIENTE-B")
    export = list_policy_profiles(db_session, direction="export")[0]  # "cdn" (order by name)
    sessao = create_session(
        db_session,
        _sessao_data(
            env, circ1, env["ne1_id"], afi="ipv6",
            local="2804:194C::1", remote="2804:194C::2",
            asn_local=64650, maximum_prefix=1000, maximum_prefix_threshold=80,
            prepend=2, shutdown=True, export_profile_id=export.id,
            description="sessão v6",
        ),
        actor="cli",
    )
    assert sessao.asn_local == 64650
    assert sessao.export_profile_id == export.id
    assert [s.id for s in list_sessions(db_session, device_id=env["ne1_id"])] == [sessao.id]
    assert list_sessions(db_session, circuit_id=circ2) == []


def test_device_fora_do_circuito_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0004", edge_id=env["ne1_id"])
    # ne2 não é edge/backup_edge do circuito
    with pytest.raises(ValidationError, match="não é edge/backup_edge"):
        create_session(db_session, _sessao_data(env, circ_id, env["ne2_id"]), actor="cli")


def test_backup_edge_aceito(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0005", organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne1_id"], backup_edge_device_id=env["ne2_id"],
        ),
        actor="cli",
    ).id
    sessao = create_session(
        db_session, _sessao_data(env, circ_id, env["ne2_id"], local="100.64.1.1", remote="100.64.1.2"),
        actor="cli",
    )
    assert sessao.device_id == env["ne2_id"]


def test_endereco_de_familia_errada_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0006", edge_id=env["ne1_id"])
    with pytest.raises(ValidationError, match="não é um endereço ipv4"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], remote="2804:194C::2"),
            actor="cli",
        )
    with pytest.raises(ValidationError, match="local_address inválido"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], local="banana"), actor="cli"
        )
    with pytest.raises(ValidationError, match="não é um endereço ipv6"):
        create_session(
            db_session,
            _sessao_data(
                env, circ_id, env["ne1_id"], afi="ipv6",
                local="2804:194C::1", remote="200.160.0.2",
            ),
            actor="cli",
        )
    with pytest.raises(ValidationError, match="não é um endereço ipv6"):
        create_session(
            db_session,
            _sessao_data(
                env, circ_id, env["ne1_id"], afi="ipv6", local="2804:194C::1",
                remote="2804:194C::2", source_address="200.160.0.1",
            ),
            actor="cli",
        )


def test_duplicidade_mesmo_device_vrf_afi(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0007", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    # mesmo device+VRF+afi em outro circuito → conflito
    circ2 = _circuito(db_session, env, code="CIRC-0008", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    with pytest.raises(ConflictError, match="Já existe sessão ipv4 ativa no equipamento ne8k-bgp1"):
        create_session(db_session, _sessao_data(env, circ2, env["ne1_id"]), actor="cli")


def test_vrfs_diferentes_convivem_no_mesmo_device(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_pub = _circuito(db_session, env, code="CIRC-0009", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ_pub, env["ne1_id"]), actor="cli")
    circ_vrf = _circuito(db_session, env, code="CIRC-0010", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    sessao = create_session(
        db_session, _sessao_data(env, circ_vrf, env["ne1_id"], local="100.64.0.5", remote="100.64.0.6"),
        actor="cli",
    )
    assert sessao.id  # VRF diferente não colide com a pública


def test_duplicidade_mensagem_vrf_publica(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0011", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    circ2 = _circuito(db_session, env, code="CIRC-0012", edge_id=env["ne1_id"])
    with pytest.raises(ConflictError, match=r"VRF pública"):
        create_session(db_session, _sessao_data(env, circ2, env["ne1_id"], local="100.64.0.9", remote="100.64.0.10"), actor="cli")


def test_duplicidade_do_par_e_global_inclusive_invertido(db_session: Session) -> None:
    env = _ambiente(db_session)
    # par em devices diferentes: não colide por linha, colide por par (global)
    circ1 = _circuito(db_session, env, code="CIRC-0013", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    circ2 = _circuito(db_session, env, code="CIRC-0014", edge_id=env["ne2_id"])
    with pytest.raises(ConflictError, match="Já existe sessão ativa entre 100.64.0.1 e 100.64.0.2"):
        create_session(db_session, _sessao_data(env, circ2, env["ne2_id"]), actor="cli")
    # par invertido (local/remoto trocados) também colide
    with pytest.raises(ConflictError, match="Já existe sessão ativa entre 100.64.0.2 e 100.64.0.1"):
        create_session(
            db_session,
            _sessao_data(env, circ2, env["ne2_id"], local="100.64.0.2", remote="100.64.0.1"),
            actor="cli",
        )


def test_afi_diferente_nao_colide(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0015", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    sessao = create_session(
        db_session,
        _sessao_data(
            env, circ1, env["ne1_id"], afi="ipv6", local="2804:194C::1", remote="2804:194C::2",
        ),
        actor="cli",
    )
    assert sessao.afi == "ipv6"  # dual stack = 2 registros (spec §6.3)


def test_asn_local_do_device_ausente_exige_override(db_session: Session) -> None:
    env = _ambiente(db_session)
    ne_sem_asn = create_device(
        db_session, DeviceCreate(name="ne8k-semasn", management_address="10.8.0.9"), actor="cli"
    )
    link_device(db_session, env["site_id"], ne_sem_asn.id, actor="cli")
    circ_id = _circuito(db_session, env, code="CIRC-0016", edge_id=ne_sem_asn.id)
    with pytest.raises(ValidationError, match="não possui ASN; informe asn_local"):
        create_session(db_session, _sessao_data(env, circ_id, ne_sem_asn.id), actor="cli")
    sessao = create_session(
        db_session,
        _sessao_data(env, circ_id, ne_sem_asn.id, asn_local=64699, local="100.64.0.13", remote="100.64.0.14"),
        actor="cli",
    )
    assert sessao.asn_local == 64699


def test_organizacao_sem_asn_exige_asn_remote(db_session: Session) -> None:
    env = _ambiente(db_session)
    org_sem_asn = create_organization(
        db_session, OrganizationCreate(name="Cliente Sem ASN"), actor="cli"
    )
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0017", organization_id=org_sem_asn.id, site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1", edge_device_id=env["ne1_id"],
        ),
        actor="cli",
    ).id
    with pytest.raises(ValidationError, match="não possui ASN; informe asn_remote"):
        create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    sessao = create_session(
        db_session,
        _sessao_data(env, circ_id, env["ne1_id"], asn_remote=64530, local="100.64.0.17", remote="100.64.0.18"),
        actor="cli",
    )
    assert sessao.asn_remote == 64530


def test_asn_remote_diverge_da_organizacao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0018", edge_id=env["ne1_id"])
    with pytest.raises(ValidationError, match="difere do ASN 64512"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], asn_remote=64599), actor="cli"
        )


def test_asn_invalido_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0019", edge_id=env["ne1_id"])
    with pytest.raises(ValidationError, match="ASN inválido ou reservado: 23456"):
        create_session(
            db_session,
            _sessao_data(env, circ_id, env["ne1_id"], asn_local=23456, local="100.64.0.21", remote="100.64.0.22"),
            actor="cli",
        )


def test_perfil_de_direction_errada_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0020", edge_id=env["ne1_id"])
    export = list_policy_profiles(db_session, direction="export")[0]
    # catálogo só tem exportações no ciclo A → import_profile_id nunca aceita export
    with pytest.raises(ValidationError, match="não pode ser o perfil de importação"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], import_profile_id=export.id),
            actor="cli",
        )
    with pytest.raises(NotFoundError, match="Perfil 9999 não encontrado"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], export_profile_id=9999),
            actor="cli",
        )


def test_circuito_desativado_nao_recebe_sessao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0021", edge_id=env["ne1_id"])
    from gerenet.domain.services.circuits import disable_circuit

    disable_circuit(db_session, circ_id, actor="cli")
    with pytest.raises(ConflictError, match="desativado não recebe sessões"):
        create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")


def test_audita_criacao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0022", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    evento = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()[0]
    assert evento.type == "bgp_session.create"
    assert evento.details["objeto_id"] == sessao.id
    assert evento.details["depois"]["asn_remote"] == 64512  # default resolvido no dump


def test_get_e_sessao_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Sessão BGP 9999 não encontrada"):
        get_session(db_session, 9999)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py -v`
Expected: FAIL — módulo `services.bgp_sessions` inexistente (e schema `BgpSessionCreate`).

- [ ] **Step 3: Escrever o schema — acrescente ao fim de `src/gerenet/domain/schemas.py`**

```python
class BgpSessionCreate(BaseModel):
    circuit_id: int
    device_id: int
    afi: Literal["ipv4", "ipv6"]
    local_address: str = Field(min_length=1, max_length=64)
    remote_address: str = Field(min_length=1, max_length=64)
    source_address: str | None = Field(default=None, max_length=64)
    asn_local: int | None = None  # default device.asn no serviço (erro se o device não tem)
    asn_remote: int | None = None  # default organization.asn no serviço (erro se a org não tem)
    description: str | None = Field(default=None, max_length=255)
    import_profile_id: int | None = None
    export_profile_id: int | None = None
    maximum_prefix: int | None = None
    maximum_prefix_threshold: int | None = Field(default=None, ge=0, le=100)  # 0–100 (%)
    local_preference: int | None = None
    med: int | None = None
    prepend: int | None = Field(default=None, ge=0, le=10)  # 0–10
    keepalive: int | None = None
    holdtime: int | None = None
    bfd_enabled: bool = False
    graceful_restart: bool = False
    shutdown: bool = False
    allow_default_route: bool = False
```

- [ ] **Step 4: Implementar — crie `src/gerenet/domain/services/bgp_sessions.py`**

```python
"""Sessões BGP por família (§6.3) — SoT da intenção de downstreams.

Regras de unicidade do §14.1 em serviço (sem constraints UNIQUE — spec §5):
linha (device+VRF+afi) e par (local, remoto). A Task 5 acrescenta
update_session/disable_session/add_community/remove_community a este arquivo.
"""
import ipaddress

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import BgpSessionCreate
from gerenet.domain.services.circuits import get_circuit
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.services.policy_profiles import get_policy_profile
from gerenet.domain.validators import asn_valido


def _valida_endereco(afi: str, campo: str, valor: str) -> None:
    """Endereço IP válido e da família do afi (mensagens PT-BR)."""
    try:
        endereco = ipaddress.ip_address(valor)
    except ValueError as exc:
        raise ValidationError(f"{campo} inválido: {valor}.") from exc
    familia = "ipv4" if isinstance(endereco, ipaddress.IPv4Address) else "ipv6"
    if familia != afi:
        raise ValidationError(f"{campo} {valor} não é um endereço {afi}.")


def _valida_asn(valor: int | None) -> None:
    if valor is not None and not asn_valido(valor):
        raise ValidationError(f"ASN inválido ou reservado: {valor}.")


def _valida_perfil(session: Session, perfil_id: int, uso: str) -> None:
    """uso = "importação" | "exportação"; perfil precisa da direção correspondente."""
    perfil = get_policy_profile(session, perfil_id)
    esperado = "import" if uso == "importação" else "export"
    if perfil.direction != esperado:
        raise ValidationError(
            f"Perfil {perfil.name} tem direção {perfil.direction} e não pode ser "
            f"o perfil de {uso} da sessão."
        )


def _vrf_texto(circuito: models.Circuit) -> str:
    return circuito.vrf or "pública"


def _colidente_linha(
    session: Session, *, device_id: int, afi: str, vrf: str | None, ignorar_id: int | None = None
) -> models.BgpSession | None:
    """Outra sessão ativa no mesmo (device, VRF do circuito, afi) — spec §4."""
    stmt = (
        select(models.BgpSession, models.Circuit)
        .join(models.Circuit, models.BgpSession.circuit_id == models.Circuit.id)
        .where(
            models.BgpSession.admin_status.is_(True),
            models.BgpSession.device_id == device_id,
            models.BgpSession.afi == afi,
        )
    )
    for outra, circ in session.execute(stmt):
        if outra.id == ignorar_id:
            continue
        if circ.vrf == vrf:
            return outra
    return None


def _colidente_par(
    session: Session, *, local_address: str, remote_address: str, ignorar_id: int | None = None
) -> models.BgpSession | None:
    """Outra sessão ativa com o mesmo par (local, remoto) — global, par invertido inclui."""
    objetivo = frozenset(
        {int(ipaddress.ip_address(local_address)), int(ipaddress.ip_address(remote_address))}
    )
    stmt = select(models.BgpSession).where(models.BgpSession.admin_status.is_(True))
    for outra in session.scalars(stmt):
        if outra.id == ignorar_id:
            continue
        par = frozenset(
            {int(ipaddress.ip_address(outra.local_address)), int(ipaddress.ip_address(outra.remote_address))}
        )
        if par == objetivo:
            return outra
    return None


def create_session(session: Session, data: BgpSessionCreate, *, actor: str) -> models.BgpSession:
    circ = get_circuit(session, data.circuit_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe sessões.")
    device = get_device(session, data.device_id)
    if data.device_id not in (circ.edge_device_id, circ.backup_edge_device_id):
        raise ValidationError(
            f"Equipamento {device.name} não é edge/backup_edge do circuito {circ.code}."
        )
    org = get_organization(session, circ.organization_id)

    _valida_endereco(data.afi, "local_address", data.local_address)
    _valida_endereco(data.afi, "remote_address", data.remote_address)
    if data.source_address is not None:
        _valida_endereco(data.afi, "source_address", data.source_address)

    asn_local = data.asn_local if data.asn_local is not None else device.asn
    if asn_local is None:
        raise ValidationError(f"Equipamento {device.name} não possui ASN; informe asn_local.")
    _valida_asn(asn_local)
    if data.asn_remote is not None:
        if org.asn is not None and data.asn_remote != org.asn:
            raise ValidationError(
                f"asn_remote {data.asn_remote} difere do ASN {org.asn} da organização {org.name}."
            )
        asn_remote = data.asn_remote
    elif org.asn is not None:
        asn_remote = org.asn
    else:
        raise ValidationError(f"Organização {org.name} não possui ASN; informe asn_remote.")
    _valida_asn(asn_remote)

    if data.import_profile_id is not None:
        _valida_perfil(session, data.import_profile_id, "importação")
    if data.export_profile_id is not None:
        _valida_perfil(session, data.export_profile_id, "exportação")

    if _colidente_linha(
        session, device_id=data.device_id, afi=data.afi, vrf=circ.vrf
    ) is not None:
        raise ConflictError(
            f"Já existe sessão {data.afi} ativa no equipamento {device.name} "
            f"(VRF {_vrf_texto(circ)})."
        )
    if _colidente_par(
        session, local_address=data.local_address, remote_address=data.remote_address
    ) is not None:
        raise ConflictError(
            f"Já existe sessão ativa entre {data.local_address} e {data.remote_address}."
        )

    dump = data.model_dump()
    dump["asn_local"] = asn_local
    dump["asn_remote"] = asn_remote
    sessao = models.BgpSession(**dump)
    session.add(sessao)
    try:
        session.flush()  # valida as FKs antes da auditoria
        registrar(
            session, tipo="bgp_session.create", ator=actor, objeto="bgp_session",
            objeto_id=sessao.id, antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "Não foi possível criar a sessão BGP: conflito de integridade."
        ) from exc
    session.refresh(sessao)
    return sessao


def get_session(session: Session, session_id: int) -> models.BgpSession:
    sessao = session.get(models.BgpSession, session_id)
    if sessao is None:
        raise NotFoundError(f"Sessão BGP {session_id} não encontrada.")
    return sessao


def list_sessions(
    session: Session,
    circuit_id: int | None = None,
    device_id: int | None = None,
    include_disabled: bool = False,
) -> list[models.BgpSession]:
    stmt = select(models.BgpSession).order_by(models.BgpSession.id)
    if not include_disabled:
        stmt = stmt.where(models.BgpSession.admin_status.is_(True))
    if circuit_id is not None:
        stmt = stmt.where(models.BgpSession.circuit_id == circuit_id)
    if device_id is not None:
        stmt = stmt.where(models.BgpSession.device_id == device_id)
    return list(session.scalars(stmt))
```

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py -v`
Expected: PASS (17 testes). Depois rode a suíte inteira: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q` — deve seguir verde.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/bgp_sessions.py tests/domain/test_bgp_sessions_service.py
git commit -m "feat(SoT): sessões BGP — criação com regras §14.1 (device+VRF+afi, par, ASNs, direção de perfis)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Sessões BGP — update, disable e associação de communities

**Files:**
- Modify: `src/gerenet/domain/services/bgp_sessions.py` (acrescenta funções — arquivo criado na Task 4)
- Modify: `src/gerenet/domain/schemas.py` (schema `BgpSessionUpdate`)
- Modify: `tests/domain/test_bgp_sessions_service.py` (acrescenta testes e imports)

**Interfaces:**
- Consumes: funções e helpers da Task 4 (`create_session`, `get_session`, `_valida_endereco`, `_valida_asn`, `_valida_perfil`, `_colidente_linha`, `_colidente_par`, `_vrf_texto`), `get_community`/`list_communities` (Task 2), modelos da Task 1.
- Produces: `update_session(session, session_id, data: BgpSessionUpdate, *, actor) -> models.BgpSession` — revalida o estado mesclado ignorando a própria sessão (ruling 7); campos not-null rejeitam null explícito (`<campo> é obrigatório.`); auditoria `bgp_session.update` com antes/depois = apenas os campos alterados; `disable_session(session, session_id, *, actor) -> models.BgpSession` — idempotente, audita só a transição (`bgp_session.disable`); `add_community(session, session_id, community_id, *, actor) -> models.BgpSession` e `remove_community(session, session_id, community_id, *, actor) -> models.BgpSession` — sem transição = no-op sem evento (ruling 12); auditoria `bgp_session.add_community` (depois={community_id, community}) e `bgp_session.remove_community` (antes={community_id, community}).

- [ ] **Step 1: Escrever o schema — acrescente ao fim de `src/gerenet/domain/schemas.py`**

```python
class BgpSessionUpdate(BaseModel):
    # Not-null na prática (ruling 7): null explícito nesses campos é rejeitado
    # no serviço com "<campo> é obrigatório."; os demais aceitam null = limpar.
    circuit_id: int | None = None
    device_id: int | None = None
    afi: Literal["ipv4", "ipv6"] | None = None
    local_address: str | None = Field(default=None, min_length=1, max_length=64)
    remote_address: str | None = Field(default=None, min_length=1, max_length=64)
    asn_local: int | None = None
    asn_remote: int | None = None
    source_address: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    import_profile_id: int | None = None
    export_profile_id: int | None = None
    maximum_prefix: int | None = None
    maximum_prefix_threshold: int | None = Field(default=None, ge=0, le=100)
    local_preference: int | None = None
    med: int | None = None
    prepend: int | None = Field(default=None, ge=0, le=10)
    keepalive: int | None = None
    holdtime: int | None = None
    bfd_enabled: bool | None = None
    graceful_restart: bool | None = None
    shutdown: bool | None = None
    allow_default_route: bool | None = None
```

- [ ] **Step 2: Acrescentar os testes que falham — `tests/domain/test_bgp_sessions_service.py`**

Acrescente ao arquivo (complementando os imports do topo com `BgpSessionUpdate`, `disable_session`, `update_session`, `add_community`, `remove_community` de `gerenet.domain.services.bgp_sessions` e `list_communities` de `gerenet.domain.services.communities`):

```python
def test_update_altera_campos_e_audita_delta(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0030", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    atualizada = update_session(
        db_session, sessao.id, BgpSessionUpdate(description="sessão principal", med=50),
        actor="cli",
    )
    assert atualizada.description == "sessão principal"
    assert atualizada.med == 50
    evento = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()[0]
    assert evento.type == "bgp_session.update"
    assert evento.details["antes"] == {"description": None, "med": None}
    assert evento.details["depois"] == {"description": "sessão principal", "med": 50}


def test_update_null_explicito_em_campo_obrigatorio_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0031", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    for campo in ("circuit_id", "device_id", "afi", "local_address", "remote_address", "asn_local", "asn_remote"):
        with pytest.raises(ValidationError, match=f"{campo} é obrigatório"):
            update_session(db_session, sessao.id, BgpSessionUpdate(**{campo: None}), actor="cli")


def test_update_null_explicito_limpa_campo_opcional(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0032", edge_id=env["ne1_id"])
    sessao = create_session(
        db_session,
        _sessao_data(
            env, circ_id, env["ne1_id"], description="com descrição",
            source_address="100.64.0.1", maximum_prefix=500,
        ),
        actor="cli",
    )
    atualizada = update_session(
        db_session, sessao.id,
        BgpSessionUpdate(description=None, source_address=None, maximum_prefix=None),
        actor="cli",
    )
    assert atualizada.description is None
    assert atualizada.source_address is None
    assert atualizada.maximum_prefix is None


def test_update_troca_device_para_backup_e_revalida(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0033", organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne1_id"], backup_edge_device_id=env["ne2_id"],
        ),
        actor="cli",
    ).id
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    atualizada = update_session(db_session, sessao.id, BgpSessionUpdate(device_id=env["ne2_id"]), actor="cli")
    assert atualizada.device_id == env["ne2_id"]
    # asn_local continua o da criação (64600) — snapshot da intenção, não re-deriva


def test_update_para_device_fora_do_circuito_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0034", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    with pytest.raises(ValidationError, match="não é edge/backup_edge"):
        update_session(db_session, sessao.id, BgpSessionUpdate(device_id=env["ne2_id"]), actor="cli")


def test_update_colide_com_outra_sessao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_a = _circuito(db_session, env, code="CIRC-0035", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    create_session(db_session, _sessao_data(env, circ_a, env["ne1_id"]), actor="cli")
    # segunda sessão em VRF diferente convive…
    circ_b = _circuito(db_session, env, code="CIRC-0036", edge_id=env["ne1_id"])
    sessao_b = create_session(
        db_session,
        _sessao_data(env, circ_b, env["ne1_id"], local="100.64.2.1", remote="100.64.2.2"),
        actor="cli",
    )
    # …mas mudar a sessão B para a VRF CLIENTE-A colide com a sessão A
    with pytest.raises(ConflictError, match="Já existe sessão ipv4 ativa no equipamento ne8k-bgp1"):
        update_session(
            db_session, sessao_b.id, BgpSessionUpdate(circuit_id=circ_a), actor="cli"
        )


def test_update_mantem_a_propria_linha_fora_da_colisao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0037", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    # reenviar os próprios valores não colide consigo mesma
    atualizada = update_session(
        db_session, sessao.id,
        BgpSessionUpdate(local_address="100.64.0.1", remote_address="100.64.0.2",
                         description="no-op de conteúdo"),
        actor="cli",
    )
    assert atualizada.description == "no-op de conteúdo"


def test_disable_idempotente_audita_uma_transicao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0038", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    disable_session(db_session, sessao.id, actor="cli")
    assert get_session(db_session, sessao.id).admin_status is False
    assert list_sessions(db_session) == []
    assert [s.id for s in list_sessions(db_session, include_disabled=True)] == [sessao.id]

    disable_session(db_session, sessao.id, actor="cli")  # repetido: no-op sem evento
    eventos = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "bgp_session.disable")
    ).all()
    assert len(eventos) == 1


def test_add_remove_community_com_auditoria(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0039", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    com = list_communities(db_session)[0]

    add_community(db_session, sessao.id, com.id, actor="cli")
    add_community(db_session, sessao.id, com.id, actor="cli")  # repetida: no-op sem evento
    vinculos = db_session.scalars(
        select(models.BgpSessionCommunity).where(
            models.BgpSessionCommunity.session_id == sessao.id
        )
    ).all()
    assert len(vinculos) == 1

    evento = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()[0]
    assert evento.type == "bgp_session.add_community"
    assert evento.details["depois"] == {"community_id": com.id, "community": com.name}

    remove_community(db_session, sessao.id, com.id, actor="cli")
    assert db_session.scalars(
        select(models.BgpSessionCommunity).where(
            models.BgpSessionCommunity.session_id == sessao.id
        )
    ).all() == []
    remove_community(db_session, sessao.id, com.id, actor="cli")  # repetido: no-op
    evento = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()[0]
    assert evento.type == "bgp_session.remove_community"
    assert evento.details["antes"] == {"community_id": com.id, "community": com.name}
    assert evento.details["depois"] is None


def test_community_inexistente_na_associacao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0040", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    with pytest.raises(NotFoundError, match="Community 9999 não encontrada"):
        add_community(db_session, sessao.id, 9999, actor="cli")
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py -v`
Expected: os testes novos FAIL — `update_session`/`disable_session`/`add_community`/`remove_community` inexistentes (os da Task 4 seguem PASS).

- [ ] **Step 4: Implementar — acrescente ao fim de `src/gerenet/domain/services/bgp_sessions.py`**

(Use os helpers já existentes no arquivo — não os redefina. Acrescente `BgpSessionUpdate` ao import de schemas e `get_community` ao import de communities.)

```python
_NOTA_NULL_OBRIGATORIO = ("circuit_id", "device_id", "afi", "local_address", "remote_address", "asn_local", "asn_remote")


def update_session(
    session: Session, session_id: int, data: BgpSessionUpdate, *, actor: str
) -> models.BgpSession:
    """Atualiza uma sessão revalidando o estado mesclado contra as regras (ruling 7)."""
    sessao = get_session(session, session_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return sessao
    for campo in _NOTA_NULL_OBRIGATORIO:
        if campo in mudancas and mudancas[campo] is None:
            raise ValidationError(f"{campo} é obrigatório.")

    circ_id = mudancas.get("circuit_id", sessao.circuit_id)
    device_id = mudancas.get("device_id", sessao.device_id)
    afi = mudancas.get("afi", sessao.afi)
    local = mudancas.get("local_address", sessao.local_address)
    remote = mudancas.get("remote_address", sessao.remote_address)
    asn_local = mudancas.get("asn_local", sessao.asn_local)
    asn_remote = mudancas.get("asn_remote", sessao.asn_remote)
    source = mudancas.get("source_address", sessao.source_address)

    circ = get_circuit(session, circ_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe sessões.")
    device = get_device(session, device_id)
    if device_id not in (circ.edge_device_id, circ.backup_edge_device_id):
        raise ValidationError(
            f"Equipamento {device.name} não é edge/backup_edge do circuito {circ.code}."
        )
    org = get_organization(session, circ.organization_id)

    _valida_endereco(afi, "local_address", local)
    _valida_endereco(afi, "remote_address", remote)
    if source is not None:
        _valida_endereco(afi, "source_address", source)
    _valida_asn(asn_local)
    _valida_asn(asn_remote)
    if org.asn is not None and asn_remote != org.asn:
        raise ValidationError(
            f"asn_remote {asn_remote} difere do ASN {org.asn} da organização {org.name}."
        )
    for campo_perfil, uso in (("import_profile_id", "importação"), ("export_profile_id", "exportação")):
        perfil_id = mudancas.get(campo_perfil, getattr(sessao, campo_perfil))
        if perfil_id is not None:
            _valida_perfil(session, perfil_id, uso)

    if _colidente_linha(
        session, device_id=device_id, afi=afi, vrf=circ.vrf, ignorar_id=sessao.id
    ) is not None:
        raise ConflictError(
            f"Já existe sessão {afi} ativa no equipamento {device.name} (VRF {_vrf_texto(circ)})."
        )
    if _colidente_par(
        session, local_address=local, remote_address=remote, ignorar_id=sessao.id
    ) is not None:
        raise ConflictError(f"Já existe sessão ativa entre {local} e {remote}.")

    antes = {campo: getattr(sessao, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(sessao, campo, valor)
    try:
        registrar(
            session, tipo="bgp_session.update", ator=actor, objeto="bgp_session",
            objeto_id=sessao.id, antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            f"Não foi possível atualizar a sessão BGP {session_id}: conflito de integridade."
        ) from exc
    session.refresh(sessao)
    return sessao


def disable_session(session: Session, session_id: int, *, actor: str) -> models.BgpSession:
    sessao = get_session(session, session_id)
    if sessao.admin_status is False:
        return sessao
    sessao.admin_status = False
    registrar(
        session, tipo="bgp_session.disable", ator=actor, objeto="bgp_session",
        objeto_id=sessao.id, antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return sessao


def add_community(
    session: Session, session_id: int, community_id: int, *, actor: str
) -> models.BgpSession:
    """Associa uma community à sessão — repetida vira no-op sem evento (ruling 12)."""
    sessao = get_session(session, session_id)
    com = get_community(session, community_id)
    existe = session.scalars(
        select(models.BgpSessionCommunity).where(
            models.BgpSessionCommunity.session_id == sessao.id,
            models.BgpSessionCommunity.community_id == community_id,
        )
    ).first()
    if existe is not None:
        return sessao
    session.add(models.BgpSessionCommunity(session_id=sessao.id, community_id=community_id))
    try:
        session.flush()
        registrar(
            session, tipo="bgp_session.add_community", ator=actor, objeto="bgp_session",
            objeto_id=sessao.id, antes=None,
            depois={"community_id": community_id, "community": com.name},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "Não foi possível associar a community à sessão: conflito de integridade."
        ) from exc
    return sessao


def remove_community(
    session: Session, session_id: int, community_id: int, *, actor: str
) -> models.BgpSession:
    """Remove a associação (linha N:N deletável; trilha na auditoria — ruling 13)."""
    sessao = get_session(session, session_id)
    com = get_community(session, community_id)
    vinculo = session.scalars(
        select(models.BgpSessionCommunity).where(
            models.BgpSessionCommunity.session_id == sessao.id,
            models.BgpSessionCommunity.community_id == community_id,
        )
    ).first()
    if vinculo is None:
        return sessao  # sem transição, sem evento
    antes = {"community_id": community_id, "community": com.name}
    session.delete(vinculo)
    registrar(
        session, tipo="bgp_session.remove_community", ator=actor, objeto="bgp_session",
        objeto_id=sessao.id, antes=antes, depois=None,
    )
    session.commit()
    return sessao
```

Atualize os imports do arquivo: em `from gerenet.domain.schemas import BgpSessionCreate` passe a `from gerenet.domain.schemas import BgpSessionCreate, BgpSessionUpdate`; acrescente `from gerenet.domain.services.communities import get_community`.

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py -v`
Expected: PASS — 17 da Task 4 + 9 novos (26 no total; o número real = funções definidas no arquivo). Depois rode a suíte inteira: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q` — deve seguir verde.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/bgp_sessions.py tests/domain/test_bgp_sessions_service.py
git commit -m "feat(SoT): sessões BGP — update com revalidação, disable e associação de communities auditada

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Verificação final do plano (após a última task)

- Suíte toda verde: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q`.
- `uv run alembic heads` aponta para `<rev>_bgp_sot` (o id gerado na Task 1) e a migration está aplicada nos dois bancos (dev e test) — conferir com `uv run alembic current` nas duas URLs.
- `graphify update .` para manter o grafo do repositório atualizado (regra do repositório após modificar código).
- Árvore limpa (sem arquivos fora do commit).
