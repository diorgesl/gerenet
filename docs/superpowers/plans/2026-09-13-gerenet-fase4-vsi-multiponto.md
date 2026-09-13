# VSI multiponto (Fase 4, parte 3) — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provisionar VSI multiponto de ponta a ponta (ACs por PE, render por equipamento, CR de escopo `vsi` com N steps, pré-check de LDP, pós-check em três níveis e rollback/reconciliação), fechando a Fase 4.

**Architecture:** O cadastro passa a criar um `ServiceEndpoint` por PE com VLAN de AC reservada por equipamento e a interface derivada do VID (`Vlanif<vid>`). O render gera dois blocos por PE (o VSI e o AC) a partir de templates Jinja2; a CR de escopo `vsi` reusa a máquina de estados do ciclo D e o replanejamento da Frente A. O parser do `display vsi verbose` passa a ler os três níveis e o `sincronizar_mpls` atualiza o estado de cada AC.

**Tech Stack:** Python 3.13, SQLAlchemy, Alembic, FastAPI, Jinja2, TextFSM, pytest, ruff, React + Vite + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-13-gerenet-fase4-vsi-multiponto-design.md`

## Global Constraints

- Artefatos em português (PT-BR): nomes de teste, docstrings, mensagens de commit e comentários.
- Sem segredos em código, fixtures ou planos.
- Comandos de verificação: `uv run pytest -q`, `uv run ruff check src tests`, `cd web && npm run build && npm run test`.
- Implementação em worktree isolada, criada antes do primeiro commit de código.
- Comandos VRP do render, copiados da captura real do switch (`sw-6730-aggr-tecmais-01`) e da fixture `tests/fixtures/huawei_vrp/s6730_display_vsi_verbose.txt`:
  - o VSI é `vsi <VRP-NAME> static`, com `vsi-id`, `flow-label` e `peer` **dentro de `pwsignal ldp`**;
  - `mtu` e `description` são do VSI, irmãos do `pwsignal`;
  - o AC é `vlan <vid>` + `interface Vlanif<vid>` + `l2 binding vsi <VRP-NAME>`;
  - a remoção desfaz só o binding e o VSI, na ordem binding → VSI.
- Nunca afirmar que um teste passa sem rodá-lo.

---

### Task 1: Modelo, migração e cadastro de VSI com ACs

**Files:**
- Create: `alembic/versions/9b1f7c4e2a05_vsi_multiponto.py`
- Modify: `src/gerenet/domain/models.py` (`VsiService`, `ServiceEndpoint.vsi`, `ChangeRequest`)
- Modify: `src/gerenet/domain/schemas.py` (`VsiEndpointIn`, `VsiCreate`, `VsiOut`, `ChangeRequestCreate`)
- Modify: `src/gerenet/domain/services/mpls.py` (`_vsi`, `create_vsi`, `out_vsi`)
- Test: `tests/domain/test_vsi_service.py`, `tests/api/test_mpls_api.py`

**Interfaces:**
- Produces: `VsiEndpointIn(device_id: int, vid: int | None = None, mtu: int | None = None)`; `VsiService.endpoints` (relationship para `ServiceEndpoint`); `create_vsi` passa a criar uma linha em `service_endpoints` (`kind='vsi'`, `interface=f"Vlanif{vid}"`) e uma em `vsi_members` por endpoint; `VsiOut.endpoints: list[VsiEndpointOut]`; `ChangeRequest.vsi_id` e `ChangeRequestCreate.vsi_id`.
- Consumes: `reservar_vlan_ac` (existente), `proximo_vsi_id` (existente), `naming.vsi_nome` (existente).

- [ ] **Step 1: Escrever a migração**

Crie `alembic/versions/9b1f7c4e2a05_vsi_multiponto.py`:

```python
"""VSI multiponto: flow_label/description e vsi_id na CR (Fase 4, parte 3)

Revision ID: 9b1f7c4e2a05
Revises: e48a9c6b2d71
Create Date: 2026-09-13 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9b1f7c4e2a05'
down_revision: str | Sequence[str] | None = 'e48a9c6b2d71'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Campos do VSI multiponto e o vínculo da CR de escopo vsi."""
    op.add_column(
        "vsi_services",
        sa.Column("flow_label", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("vsi_services", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("change_requests", sa.Column("vsi_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_change_requests_vsi_id", "change_requests", "vsi_services", ["vsi_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_change_requests_vsi_id", "change_requests", type_="foreignkey")
    op.drop_column("change_requests", "vsi_id")
    op.drop_column("vsi_services", "description")
    op.drop_column("vsi_services", "flow_label")
```

- [ ] **Step 2: Rodar a migração e conferir os heads**

Run: `uv run alembic upgrade head && uv run alembic heads`
Expected: `e48a9c6b2d71 -> 9b1f7c4e2a05, VSI multiponto...` e um único head `9b1f7c4e2a05`.

- [ ] **Step 3: Escrever os testes que falham**

Em `tests/domain/test_vsi_service.py`, troque os usos de `members=[...]` por `endpoints=[...]` (importe `VsiEndpointIn` junto dos outros schemas) e adicione ao final:

```python
def _dominio_com_dois_membros(db_session, sufixo: str):
    """(d1, d2, dom) com site, devices e membros LDP prontos para um VSI."""
    site = create_site(db_session, SiteCreate(name=f"pop-vsi-{sufixo}"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name=f"sw-a-{sufixo}", management_address=f"10.9.1.{len(sufixo)}1", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name=f"sw-b-{sufixo}", management_address=f"10.9.2.{len(sufixo)}1", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name=f"dom-{sufixo}"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.7.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.7.2"), actor="cli")
    return d1, d2, dom


def test_vsi_cria_ac_com_vid_default_igual_ao_vsi_id(db_session):
    """Sem vid explícito a ponta usa o VSI-ID, a convenção da operação."""
    d1, d2, dom = _dominio_com_dois_membros(db_session, "dflt")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente default", vsi_id=600,
        endpoints=[VsiEndpointIn(device_id=d1.id), VsiEndpointIn(device_id=d2.id)],
    ), actor="cli")
    assert sorted(ep.interface for ep in vsi.endpoints) == ["Vlanif600", "Vlanif600"]
    assert sorted(ep.vlan.vid for ep in vsi.endpoints if ep.vlan is not None) == [600, 600]
    assert {ep.device_id for ep in vsi.endpoints} == {d1.id, d2.id}
    assert len(vsi.endpoints[0].interface) == len("Vlanif600")


def test_vsi_aceita_vid_explicito_e_deriva_a_interface(db_session):
    d1, d2, dom = _dominio_com_dois_membros(db_session, "expl")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente explicito", vsi_id=601, flow_label=True,
        description="VSI do cliente",
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=900, mtu=9100),
                   VsiEndpointIn(device_id=d2.id, vid=901)],
    ), actor="cli")
    por_device = {ep.device_id: ep for ep in vsi.endpoints}
    assert por_device[d1.id].interface == "Vlanif900"
    assert por_device[d2.id].interface == "Vlanif901"
    assert vsi.flow_label is True
    assert vsi.description == "VSI do cliente"


def test_vsi_recusa_endpoint_duplicado(db_session):
    d1, _, dom = _dominio_com_dois_membros(db_session, "dupl")
    with pytest.raises(ValidationError, match="duplicado"):
        create_vsi(db_session, VsiCreate(
            domain_id=dom.id, name="cliente duplicado", vsi_id=602,
            endpoints=[VsiEndpointIn(device_id=d1.id), VsiEndpointIn(device_id=d1.id)],
        ), actor="cli")


def test_vsi_recusa_vid_ocupado_no_mesmo_equipamento(db_session):
    d1, d2, dom = _dominio_com_dois_membros(db_session, "ocup")
    create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="primeiro", vsi_id=603,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=800), VsiEndpointIn(device_id=d2.id, vid=800)],
    ), actor="cli")
    with pytest.raises(ConflictError):
        create_vsi(db_session, VsiCreate(
            domain_id=dom.id, name="segundo", vsi_id=604,
            endpoints=[VsiEndpointIn(device_id=d1.id, vid=800), VsiEndpointIn(device_id=d2.id, vid=801)],
        ), actor="cli")


def test_vsi_cadastro_exige_ao_menos_um_endpoint(db_session):
    _, _, dom = _dominio_com_dois_membros(db_session, "vazio")
    with pytest.raises(Exception):
        VsiCreate(domain_id=dom.id, name="sem ponta", vsi_id=605, endpoints=[])
```

- [ ] **Step 4: Rodar e confirmar que falham**

Run: `uv run pytest tests/domain/test_vsi_service.py -q`
Expected: FAIL — `ImportError` de `VsiEndpointIn` e, nos testes que usam `members`, erro de validação do schema.

- [ ] **Step 5: Implementar os modelos**

Em `src/gerenet/domain/models.py`, no `VsiService`, depois de `mac_limit`, acrescente:

```python
    flow_label: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text())
```

Ainda no `VsiService`, junto das outras relationships, acrescente:

```python
    endpoints: Mapped[list["ServiceEndpoint"]] = relationship(
        back_populates="vsi", order_by="ServiceEndpoint.device_id",
    )
```

No `ServiceEndpoint`, troque a relationship do VSI por:

```python
    vsi: Mapped["VsiService | None"] = relationship(back_populates="endpoints")
```

No `ChangeRequest`, logo depois de `l2vc_id`:

```python
    vsi_id: Mapped[int | None] = mapped_column(ForeignKey("vsi_services.id"))
```

- [ ] **Step 6: Implementar os schemas**

Em `src/gerenet/domain/schemas.py`, imediatamente antes de `VsiCreate`:

```python
class VsiEndpointIn(BaseModel):
    device_id: int
    # None ⇒ o VID assume o vsi_id do serviço (convenção da operação)
    vid: int | None = Field(default=None, ge=2, le=4094)
    mtu: int | None = Field(default=None, ge=576, le=9216)
```

Troque `members: list[int] = Field(default_factory=list, min_length=1)` em `VsiCreate` por:

```python
    flow_label: bool = False
    description: str | None = Field(default=None, max_length=255)
    endpoints: list[VsiEndpointIn] = Field(default_factory=list, min_length=1)
```

Troque `VsiMemberOut`/`VsiOut.members` por `VsiEndpointOut`/`VsiOut.endpoints`:

```python
class VsiEndpointOut(BaseModel):
    device_id: int
    device_name: str | None
    interface: str
    vid: int | None
    mtu: int | None
    operational_status: str
```

Em `VsiOut`, troque `members: list[VsiMemberOut]` por `endpoints: list[VsiEndpointOut]` e acrescente `flow_label: bool` e `description: str | None`.

Em `ChangeRequestCreate`, acrescente o campo e o ramo do validador, trocando o bloqueio atual:

```python
    vsi_id: int | None = None  # escopo vsi (fase 4, parte 3)
```

```python
        if self.escopo == "vsi" and self.vsi_id is None:
            raise ValueError("vsi_id é obrigatório para escopo 'vsi'.")
```

- [ ] **Step 7: Implementar o cadastro no serviço**

Em `src/gerenet/domain/services/mpls.py`, em `_vsi`, acrescente os endpoints ao carregamento:

```python
            selectinload(models.VsiService.endpoints).selectinload(models.ServiceEndpoint.device),
            selectinload(models.VsiService.endpoints).selectinload(models.ServiceEndpoint.vlan),
```

Em `create_vsi`, troque o bloco que valida e cria os membros por:

```python
    endpoints = data.endpoints
    if len({ep.device_id for ep in endpoints}) != len(endpoints):
        raise ValidationError("Endpoint duplicado no mesmo VSI: um por equipamento.")
    devices = [get_device(session, ep.device_id) for ep in endpoints]
    for dev in devices:
        if _membro_loopback(session, dom.id, dev.id) is None:
            raise ValidationError(f"Equipamento {dev.name} sem loopback LDP no domínio (membro inexistente).")
    vsi = models.VsiService(
        domain_id=dom.id, vsi_id=vsi_id, name=nome, vrp_name=vrp,
        mtu=data.mtu, split_horizon=data.split_horizon, mac_learning=data.mac_learning,
        mac_limit=data.mac_limit, flow_label=data.flow_label, description=data.description,
    )
    session.add(vsi)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"VSI-ID ou nome já em uso no domínio {dom.name}.") from exc
    for ep in endpoints:
        vid = ep.vid if ep.vid is not None else vsi_id
        vlan = reservar_vlan_ac(session, device_id=ep.device_id, vid=vid, actor=actor)
        dono = session.scalars(
            select(models.ServiceEndpoint.vsi_id).where(
                models.ServiceEndpoint.vlan_id == vlan.id,
                models.ServiceEndpoint.vsi_id != vsi.id,
            ).limit(1)
        ).first()
        if dono is not None:
            session.rollback()
            raise ConflictError(f"VLAN {vlan.vid} já pertence ao VSI {dono}.")
        session.add(models.ServiceEndpoint(
            kind="vsi", vsi_id=vsi.id, device_id=ep.device_id, interface=f"Vlanif{vid}",
            encapsulation="dot1q", vlan_id=vlan.id, mtu=ep.mtu or data.mtu,
        ))
        session.add(models.VsiMember(vsi_id=vsi.id, device_id=ep.device_id))
    session.flush()
```

Em `out_vsi`, troque `members=[_out_vsi_membro(m) for m in svc.members]` por:

```python
        flow_label=svc.flow_label,
        description=svc.description,
        endpoints=[
            VsiEndpointOut(
                device_id=ep.device_id,
                device_name=ep.device.name if ep.device is not None else None,
                interface=ep.interface,
                vid=ep.vlan.vid if ep.vlan is not None else None,
                mtu=ep.mtu,
                operational_status=ep.operational_status,
            )
            for ep in svc.endpoints
        ],
```

(importe `VsiEndpointOut` no topo do módulo, junto dos outros schemas de saida, e remova `_out_vsi_membro` se ficar sem uso).

- [ ] **Step 8: Rodar os testes de domínio e ajustar os consumidores que quebrarem**

Run: `uv run pytest tests/domain -q`
Expected: PASS depois de trocar `members=` por `endpoints=` nos testes que usavam o schema antigo. Se `tests/domain/test_mpls_sync.py` montar VSI com `members=`, troque por `endpoints=[VsiEndpointIn(device_id=...)]`.

- [ ] **Step 9: Rodar API e CLI e ajustar**

Run: `uv run pytest tests/api tests/cli -q`
Expected: PASS. Em `tests/api/test_mpls_api.py`, os payloads de `members` viram `endpoints` (`[{"device_id": 1, "vid": 600}, ...]`) e as asserções de `members` viram `endpoints`.

- [ ] **Step 10: Commit**

```bash
git add alembic/versions/9b1f7c4e2a05_vsi_multiponto.py src/gerenet/domain/models.py \
        src/gerenet/domain/schemas.py src/gerenet/domain/services/mpls.py \
        tests/domain/test_vsi_service.py tests/domain/test_mpls_sync.py tests/api/test_mpls_api.py
git commit -m "feat(vsi): ACs por PE com Vlanif derivada do VID e vsi_id na CR"
```

---

### Task 2: Parser nos três níveis e sincronização por AC

**Files:**
- Modify: `src/gerenet/automation/parsers/huawei_vrp/textfsm/vsi.template`
- Modify: `src/gerenet/automation/parsers/huawei_vrp/merge.py` (`normaliza_vsi`)
- Modify: `src/gerenet/domain/services/mpls.py` (`sincronizar_mpls`)
- Test: `tests/automation/test_parsers_mpls.py`, `tests/domain/test_mpls_sync.py`

**Interfaces:**
- Produces: recurso `vsi` como `list[{name: str, vsi_id: int, estado: str, mtu: int | None, peers: list[{peer: str, estado: str | None}], acs: list[{interface: str, estado: str | None}]}]`, agrupado pelo nome; grupo sem `VSI ID` próprio é descartado. `sincronizar_mpls` passa a atualizar o `operational_status` de cada `ServiceEndpoint` de VSI pelo AC correspondente.
- Consumes: nada das tarefas anteriores (o template é independente do modelo).

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/automation/test_parsers_mpls.py`, troque `test_vsi_verbose_real` e `test_merge_vsi_normaliza_verbose` por estes e acrescente os novos:

```python
def test_vsi_verbose_tres_niveis() -> None:
    """S6730: o bloco traz VSI, peer e AC — o parse devolve uma linha por nível."""
    linhas = parse_template("vsi", _real("s6730_display_vsi_verbose.txt"))
    assert {"name": "IntechCDN", "estado": "up", "vsi_id": "2827", "mtu": "1500"} in linhas
    assert {"name": "IntechCDN", "peer": "100.127.90.255", "peer_estado": "up",
            "vsi_id": "", "ac_if": ""} in linhas
    assert {"name": "IntechCDN", "ac_if": "Vlanif2827", "ac_estado": "up",
            "vsi_id": "", "peer": ""} in linhas


def test_merge_vsi_agrupa_por_nome() -> None:
    assert merge_parsed("vsi", {"display vsi verbose": [
        {"name": "IntechCDN", "estado": "up", "vsi_id": "2827", "mtu": "1500",
         "peer": "", "peer_estado": "", "ac_if": "", "ac_estado": ""},
        {"name": "IntechCDN", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "100.127.90.255", "peer_estado": "up", "ac_if": "", "ac_estado": ""},
        {"name": "IntechCDN", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "Vlanif2827", "ac_estado": "up"},
    ]}) == [{
        "name": "IntechCDN", "vsi_id": 2827, "estado": "up", "mtu": 1500,
        "peers": [{"peer": "100.127.90.255", "estado": "up"}],
        "acs": [{"interface": "Vlanif2827", "estado": "up"}],
    }]


def test_merge_vsi_fixture_real() -> None:
    """Nove VSIs com ID; o bloco quebrado (nome sem ID) não entra, nem o AC dele."""
    linhas = merge_parsed("vsi", {
        "display vsi verbose": parse_template("vsi", _real("s6730_display_vsi_verbose.txt")),
    })
    assert len(linhas) == 9
    por_nome = {l["name"]: l for l in linhas}
    assert por_nome["IntechCDN"]["peers"] == [{"peer": "100.127.90.255", "estado": "up"}]
    assert por_nome["IntechCDN"]["acs"] == [{"interface": "Vlanif2827", "estado": "up"}]
    assert por_nome["VLAN4030"]["estado"] == "down"
    assert por_nome["VLAN4030"]["peers"] == [{"peer": "100.127.90.247", "estado": "down"}]
    assert por_nome["VLAN4004"]["mtu"] == 9216
    assert not any(l["name"].endswith("]") for l in linhas)


def test_merge_vsi_bloco_sem_id_descarta_o_ac_junto() -> None:
    """Bloco truncado com AC não pode herdar o VSI anterior (o nome é o único filldown)."""
    assert merge_parsed("vsi", {"display vsi verbose": [
        {"name": "BOM", "estado": "up", "vsi_id": "10", "mtu": "9100",
         "peer": "", "peer_estado": "", "ac_if": "", "ac_estado": ""},
        {"name": "BOM", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "Vlanif10", "ac_estado": "up"},
        {"name": "ORFAO]", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "Vlanif99", "ac_estado": "up"},
    ]}) == [{
        "name": "BOM", "vsi_id": 10, "estado": "up", "mtu": 9100,
        "peers": [], "acs": [{"interface": "Vlanif10", "estado": "up"}],
    }]
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `uv run pytest tests/automation/test_parsers_mpls.py -q -k vsi`
Expected: FAIL — o template atual só emite `{name, vsi_id, estado}` e não tem as chaves `mtu`/`peer`/`ac_if`.

- [ ] **Step 3: Reescrever o template**

Arquivo `src/gerenet/automation/parsers/huawei_vrp/textfsm/vsi.template` (só o `name` é `Filldown`: é ele que agrupa o bloco; o `VSI ID` fica na linha do VSI e é o que distingue um bloco real de um truncado):

```
Value Filldown name (\S+)
Value estado (\S+)
Value vsi_id (\d+)
Value mtu (\d+)
Value peer (\d+\.\d+\.\d+\.\d+)
Value peer_estado (\S+)
Value ac_if (\S+)
Value ac_estado (\S+)

Start
  ^\s*\*+\s*VSI Name\s*:\s*${name}\s*$$ -> Continue
  ^\s*MTU\s*:\s*${mtu}\s*$$ -> Continue
  ^\s*VSI State\s*:\s*${estado}\s*$$ -> Continue
  ^\s*VSI ID\s*:\s*${vsi_id}\s*$$ -> Record
  ^\s*\*Peer Router ID\s*:\s*${peer}\s*$$ -> Continue
  ^\s*Session\s*:\s*${peer_estado}\s*$$ -> Record
  ^\s*Interface Name\s*:\s*${ac_if}\s*$$ -> Continue
  ^\s*State\s*:\s*${ac_estado}\s*$$ -> Record
```

- [ ] **Step 4: Reescrever o merge**

Em `src/gerenet/automation/parsers/huawei_vrp/merge.py`, troque `normaliza_vsi` por:

```python
def normaliza_vsi(por_comando: dict[str, list[dict]]) -> list[dict]:
    """`display vsi verbose` -> um dict por VSI com peers e ACs (§9.3).

    O parse devolve uma linha por nível (VSI, peer, AC); o `name` é o único
    valor preenchido ao longo do bloco e por isso é a chave do agrupamento. O
    `vsi_id` vem da linha do próprio VSI: grupo sem ID (bloco truncado, como o
    `VLAN653_INTECH]` da rede real) é descartado inteiro, e com ele o AC que
    porventura viesse depois, que não pode ser atribuído ao VSI anterior.

    Keys: {name, vsi_id, estado, mtu, peers, acs}; `estado` desconhecido vira
    None (nunca "down" por omissão) e campo ausente não inventa valor.
    """
    grupos: dict[str, dict] = {}
    for linha in _primeiras_linhas(por_comando):
        nome = linha.get("name")
        if not nome:
            continue
        grupo = grupos.setdefault(nome, {
            "name": nome, "vsi_id": None, "estado": None, "mtu": None,
            "peers": [], "acs": [],
        })
        if linha.get("vsi_id"):
            grupo["vsi_id"] = int(linha["vsi_id"])
            grupo["estado"] = (
                "up" if str(linha.get("estado", "")).lower() == "up" else "down"
            )
            grupo["mtu"] = int(linha["mtu"]) if linha.get("mtu") else None
        if linha.get("peer"):
            grupo["peers"].append({
                "peer": linha["peer"],
                "estado": (
                    {"up": "up", "down": "down"}.get(
                        str(linha.get("peer_estado") or "").lower()
                    )
                ),
            })
        if linha.get("ac_if"):
            grupo["acs"].append({
                "interface": linha["ac_if"],
                "estado": (
                    {"up": "up", "down": "down"}.get(
                        str(linha.get("ac_estado") or "").lower()
                    )
                ),
            })
    return [g for g in grupos.values() if g["vsi_id"] is not None]
```

- [ ] **Step 5: Rodar os testes do parser**

Run: `uv run pytest tests/automation/test_parsers_mpls.py -q`
Expected: PASS.

- [ ] **Step 6: Escrever o teste da sincronização por AC**

Em `tests/domain/test_mpls_sync.py`, acrescente (o arquivo já tem o padrão de snapshot success por device):

```python
def test_sincronizar_mpls_atualiza_estado_do_ac_do_vsi(db_session):
    """O AC do VSI também é um ServiceEndpoint: o estado dele vem da coleta.

    O estado do SERVIÇO continua vindo do `VSI State` do equipamento; o do AC
    é por ponta. Um AC caído não rebaixa o serviço na SoT.
    """
    from gerenet.domain import models
    from gerenet.domain.services.mpls import sincronizar_mpls
    from gerenet.domain.schemas import (
        DeviceCreate, MplsDomainCreate, MplsMemberIn, SiteCreate, VsiCreate, VsiEndpointIn,
    )
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.mpls import add_domain_member, create_domain, create_vsi
    from gerenet.domain.services.sites import create_site

    site = create_site(db_session, SiteCreate(name="pop-sync-vsi"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-sync-a", management_address="10.9.5.1", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-sync-b", management_address="10.9.5.2", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-sync-vsi"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.4.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.4.2"), actor="cli")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="sync vsi", vsi_id=900,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=900),
                   VsiEndpointIn(device_id=d2.id, vid=900)],
    ), actor="cli")
    snap = models.DeviceSnapshot(
        device_id=d1.id, status="success", resources={"vsi": [{
            "name": vsi.vrp_name, "vsi_id": vsi.vsi_id, "estado": "up", "mtu": 1500,
            "peers": [{"peer": "10.255.4.2", "estado": "up"}],
            "acs": [{"interface": "Vlanif900", "estado": "down"}],
        }]}, errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    sincronizar_mpls(db_session, snap)
    ep = next(e for e in vsi.endpoints if e.device_id == d1.id)
    assert ep.operational_status == "down"
    assert vsi.operational_status == "up"
```

- [ ] **Step 7: Implementar a sincronização**

Em `src/gerenet/domain/services/mpls.py`, no laço do recurso `vsi` de `sincronizar_mpls`, depois de atualizar o VSI:

```python
        for ac in linha.get("acs", []) or []:
            nome_if = ac.get("interface")
            if not nome_if:
                continue
            dono = next(
                (e for e in vsi.endpoints if e.device_id == snapshot.device_id
                 and e.interface == nome_if),
                None,
            )
            if dono is not None:
                dono.operational_status = ac.get("estado") or "unknown"
```

O estado do serviço **não muda**: continua vindo do `VSI State` do equipamento, como hoje. Um AC caído não rebaixa o VSI na SoT; as duas informações convivem.

- [ ] **Step 8: Rodar os testes de sincronização e o lint**

Run: `uv run pytest tests/domain/test_mpls_sync.py tests/automation -q && uv run ruff check src tests`
Expected: PASS e `All checks passed!`.

- [ ] **Step 9: Commit**

```bash
git add src/gerenet/automation/parsers/huawei_vrp/textfsm/vsi.template \
        src/gerenet/automation/parsers/huawei_vrp/merge.py \
        src/gerenet/domain/services/mpls.py tests/automation/test_parsers_mpls.py \
        tests/domain/test_mpls_sync.py
git commit -m "feat(vsi): parser nos três níveis (VSI, pseudowire e AC) e estado por AC"
```

---

### Task 3: Render, plano, pré-check e pós-check

**Files:**
- Create: `src/gerenet/automation/templates/huawei_vrp/vsi.j2`
- Create: `src/gerenet/automation/templates/huawei_vrp/vsi_ac.j2`
- Create: `src/gerenet/automation/vsi.py`
- Test: `tests/automation/test_vsi.py` (novo)

**Interfaces:**
- Consumes: `changes.PlanoDevice`, `changes._ultimo_snapshot_ok`, `changes._bloco_para_plano`, `render.BlocoRender`, `render._render_template`, `mpls.get_vsi`, `mpls._membro_loopback` (Task 1 e 2).
- Produces: `render_vsi(session, service) -> dict[int, list[BlocoRender]]`; `estado_bloco_vsi(bloco, recursos) -> "consta" | "ausente" | "conflito"`; `plan_provision_vsi(session, service) -> list[PlanoDevice]`; `plan_remocao_vsi(session, service) -> list[PlanoDevice]`; `valida_pre_checks_vsi(session, service, device, recursos) -> str | None`; `valida_pos_vsi(session, service, snapshot) -> list[dict]`.

- [ ] **Step 1: Escrever o teste do render**

Crie `tests/automation/test_vsi.py`:

```python
"""Render, planos e pré/pós-checks do VSI multiponto — fase 4, spec §9.3."""
import pytest

from gerenet.automation import vsi as vsi_auto
from gerenet.domain.schemas import (
    DeviceCreate,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
    VsiCreate,
    VsiEndpointIn,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_vsi
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def servico(db_session):
    site = create_site(db_session, SiteCreate(name="pop-vsi-aut"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.9.3.1", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.9.3.2", site_id=site.id), actor="cli")
    d3 = create_device(db_session, DeviceCreate(
        name="sw-c", management_address="10.9.3.3", site_id=site.id), actor="cli")
    # DeviceCreate não expõe capabilities: grava direto no device (a coluna é JSON)
    d3.capabilities = ["mpls_flow_label"]
    db_session.commit()
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi-aut"), actor="cli")
    for dev, lb in ((d1, "10.255.6.1"), (d2, "10.255.6.2"), (d3, "10.255.6.3")):
        add_domain_member(db_session, dom.id,
                          MplsMemberIn(device_id=dev.id, loopback_address=lb), actor="cli")
    svc = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente acme", vsi_id=700, flow_label=True, mtu=1500,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=700),
                   VsiEndpointIn(device_id=d2.id, vid=700),
                   VsiEndpointIn(device_id=d3.id, vid=700)],
    ), actor="cli")
    return d1, d2, d3, svc


def test_render_vsi_um_bloco_por_pe_com_os_peers_dos_outros(servico, db_session):
    d1, d2, d3, svc = servico
    por_device = vsi_auto.render_vsi(db_session, svc)
    assert set(por_device) == {d1.id, d2.id, d3.id}
    texto_d1 = "\n".join(c for b in por_device[d1.id] for c in b.comandos)
    assert "vsi VSI-CLIENTE-ACME-700 static" in texto_d1
    assert "  peer 10.255.6.2" in texto_d1
    assert "  peer 10.255.6.3" in texto_d1
    assert "  peer 10.255.6.1" not in texto_d1
    assert texto_d1.count("  peer ") == 2


def test_render_vsi_flow_label_so_com_capability(servico, db_session):
    d1, d2, d3, svc = servico
    por_device = vsi_auto.render_vsi(db_session, svc)
    texto_d1 = "\n".join(c for b in por_device[d1.id] for c in b.comandos)
    texto_d3 = "\n".join(c for b in por_device[d3.id] for c in b.comandos)
    assert "flow-label both" not in texto_d1  # d1 não declara a capability
    assert "flow-label both" in texto_d3


def test_render_vsi_ac_com_vlan_e_binding(servico, db_session):
    d1, _, _, svc = servico
    blocos = vsi_auto.render_vsi(db_session, svc)[d1.id]
    ac = next(b for b in blocos if b.tipo == "vsi_ac")
    assert ac.comandos == [
        "vlan 700", "interface Vlanif700", "l2 binding vsi VSI-CLIENTE-ACME-700",
    ]
    assert [b.tipo for b in blocos] == ["vsi", "vsi_ac"]


def test_plan_remocao_vsi_desfaz_binding_antes_do_vsi(servico, db_session):
    d1, _, _, svc = servico
    from gerenet.domain import models
    snap = models.DeviceSnapshot(
        device_id=d1.id, status="success", resources={"vsi": [{
            "name": svc.vrp_name, "vsi_id": svc.vsi_id, "estado": "up", "mtu": 1500,
            "peers": [{"peer": "10.255.6.2", "estado": "up"}],
            "acs": [{"interface": "Vlanif700", "estado": "up"}],
        }]}, errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    plano = vsi_auto.plan_remocao_vsi(db_session, svc)
    item = next(p for p in plano if p.device_id == d1.id)
    tipos = [b["tipo"] for b in item.blocos]
    assert tipos == ["vsi_ac", "vsi"]
    assert item.blocos[0]["comandos"][-1] == "undo l2 binding vsi VSI-CLIENTE-ACME-700"
    assert item.blocos[1]["comandos"] == ["undo vsi VSI-CLIENTE-ACME-700"]


def test_pre_check_vsi_bloqueia_sem_coleta_de_ldp(servico, db_session):
    d1, _, _, svc = servico
    assert vsi_auto.valida_pre_checks_vsi(db_session, svc, d1, {}) is not None


def test_pos_check_vsi_marca_pseudowire_e_ac(servico, db_session):
    d1, _, _, svc = servico
    from gerenet.domain import models
    snap = models.DeviceSnapshot(
        device_id=d1.id, status="success", resources={"vsi": [{
            "name": svc.vrp_name, "vsi_id": svc.vsi_id, "estado": "up", "mtu": 1500,
            "peers": [{"peer": "10.255.6.2", "estado": "down"}],
            "acs": [{"interface": "Vlanif700", "estado": "down"}],
        }]}, errors={}, raw_files={}, duration_ms=0,
    )
    itens = vsi_auto.valida_pos_vsi(db_session, svc, snap)
    por_tipo = {i["tipo"]: i for i in itens}
    assert por_tipo["vsi.peer"]["severidade"] == "critica"
    assert por_tipo["vsi.ac"]["severidade"] == "atencao"
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `uv run pytest tests/automation/test_vsi.py -q`
Expected: FAIL — `ModuleNotFoundError: gerenet.automation.vsi`.

- [ ] **Step 3: Criar os templates**

`src/gerenet/automation/templates/huawei_vrp/vsi.j2` (forma idêntica à captura real do switch, sem o `tnl-policy` que a operação usa como default):

```
vsi {{ vrp_name }} static
{% if description %} description {{ description }}
{% endif %} pwsignal ldp
  vsi-id {{ vsi_id }}
{% if flow_label %}  flow-label both
{% endif %}{% for peer in peers %}  peer {{ peer }}
{% endfor %}{% if mtu %} mtu {{ mtu }}
{% endif %}
```

`src/gerenet/automation/templates/huawei_vrp/vsi_ac.j2`:

```
vlan {{ vid }}
interface Vlanif{{ vid }}
{% if description %} description {{ description }}
{% endif %} l2 binding vsi {{ vrp_name }}
```

- [ ] **Step 4: Criar a automação**

Crie `src/gerenet/automation/vsi.py` no molde de `automation/l2vc.py`:

```python
"""Automação VSI multiponto (spec §9.3): render, planos e pré/pós-checks.

Usa o maquinário de `changes.py` (PlanoDevice, snapshot da última coleta) e de
`render.py` (BlocoRender, templates). Dois blocos por PE, na ordem em que o VRP
aceita: o VSI primeiro e o AC depois; a remoção inverte.
"""
from sqlalchemy.orm import Session

from gerenet.automation import changes
from gerenet.automation.render import BlocoRender, _render_template
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import _membro_loopback, get_vsi

_SEM_VSI_AVISO = (
    "Sem coleta do recurso 'vsi' — plano gerado sem diff confiável; "
    "a execução re-valida (gate §5.3) e pode pular blocos já presentes."
)
_RECURSOS_VSI = ("vsi",)


def _peers(session: Session, service: models.VsiService, device_id: int) -> list[str]:
    """Loopbacks LDP dos OUTROS membros — é o que cada PE usa como peer."""
    peers: list[str] = []
    for ep in service.endpoints:
        if ep.device_id == device_id:
            continue
        loopback = _membro_loopback(session, service.domain_id, ep.device_id)
        if loopback is None:
            raise ValidationError(
                f"Par {ep.device_id} sem loopback LDP no domínio — revalide o serviço."
            )
        peers.append(loopback)
    if not peers:
        raise ValidationError("VSI sem peers: precisa de pelo menos dois membros.")
    return sorted(peers)


def render_vsi(session: Session, service: models.VsiService) -> dict[int, list[BlocoRender]]:
    """Blocos por device: `vsi` (o serviço) e `vsi_ac` (a ponta), nessa ordem."""
    service = get_vsi(session, service.id)
    por_device: dict[int, list[BlocoRender]] = {}
    for ep in service.endpoints:
        vlan = session.get(models.Vlan, ep.vlan_id) if ep.vlan_id else None
        if vlan is None:
            raise ValidationError(
                f"Ponta {ep.interface} do VSI {service.name} sem VLAN reservada."
            )
        dev = session.get(models.Device, ep.device_id)
        suporta_fc = "mpls_flow_label" in (dev.capabilities or [])
        comandos_vsi = _render_template("vsi", {
            "vrp_name": service.vrp_name,
            "description": service.description,
            "vsi_id": service.vsi_id,
            "flow_label": service.flow_label and suporta_fc,
            "peers": _peers(session, service, ep.device_id),
            "mtu": service.mtu,
        }).splitlines()
        comandos_ac = _render_template("vsi_ac", {
            "vid": vlan.vid,
            "description": service.description,
            "vrp_name": service.vrp_name,
        }).splitlines()
        por_device.setdefault(ep.device_id, []).extend([
            BlocoRender(tipo="vsi", objeto="vsi", objeto_id=service.id, comandos=comandos_vsi),
            BlocoRender(tipo="vsi_ac", objeto="vsi", objeto_id=service.id, comandos=comandos_ac),
        ])
    return por_device
```

Ainda no arquivo, os planos e as validações:

```python
def estado_bloco_vsi(bloco: dict, recursos: dict) -> str:
    """Presença do bloco no encontrado, por identidade (nome VRP e Vlanif).

    O bloco do AC é identificado pela `Vlanif<vid>` e o do VSI pelo nome VRP,
    tanto na criação quanto na remoção. O snapshot não guarda o nome do VSI
    ligado ao AC (o `display` não o mostra), então um binding de outro serviço
    aparece aqui como "consta"; quem barra esse caso é o pré-check.
    """
    comandos = bloco.get("comandos") or []
    if not comandos:
        return "ausente"
    linhas = recursos.get("vsi", []) or []
    texto = " ".join(comandos)
    m_if = re.search(r"\b(Vlanif\d+)\b", texto)
    if m_if is not None:
        iface = m_if.group(1)
        return "consta" if any(
            ac.get("interface") == iface for l in linhas for ac in (l.get("acs") or [])
        ) else "ausente"
    m_vsi = re.search(r"\bvsi (\S+)", texto)
    if m_vsi is not None:
        return "consta" if any(l.get("name") == m_vsi.group(1) for l in linhas) else "ausente"
    return "ausente"


def _recursos_snapshot(snap: models.DeviceSnapshot | None) -> tuple[dict, bool]:
    if snap is None or snap.resources is None:
        return {}, False
    return snap.resources, all(k in snap.resources for k in _RECURSOS_VSI)


def plan_provision_vsi(session: Session, service: models.VsiService) -> list[changes.PlanoDevice]:
    """Plano de criação por PE — blocos do render, menos os já presentes (§5.1)."""
    plano: list[changes.PlanoDevice] = []
    for device_id, blocos in render_vsi(session, service).items():
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos, tem = _recursos_snapshot(snap)
        if tem:
            a_aplicar = [
                changes._bloco_para_plano(b, "create")
                for b in blocos
                if estado_bloco_vsi(changes._bloco_para_plano(b, "create"), recursos) != "consta"
            ]
        else:
            a_aplicar = [changes._bloco_para_plano(b, "create") for b in blocos]
        plano.append(changes.PlanoDevice(
            device_id=device_id, blocos=a_aplicar,
            baseline_snapshot_id=snap.id if snap is not None and tem else None,
            aviso=None if tem else _SEM_VSI_AVISO,
        ))
    return plano


def plan_remocao_vsi(session: Session, service: models.VsiService) -> list[changes.PlanoDevice]:
    """Blocos delete por PE, do AC para o VSI (o VRP recusa remover VSI com AC ligado)."""
    plano: list[changes.PlanoDevice] = []
    for device_id, blocos in render_vsi(session, service).items():
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos, tem = _recursos_snapshot(snap)
        if not tem:
            raise ValidationError(
                "Sem snapshot recente com 'vsi' para gerar a remoção — colete antes (§5.2)."
            )
        a_remover: list[dict] = []
        por_tipo = {b.tipo: b for b in blocos}
        for tipo in ("vsi_ac", "vsi"):
            bloco = por_tipo.get(tipo)
            if bloco is None:
                continue
            item = changes._bloco_para_plano(bloco, "delete")
            if tipo == "vsi":
                # `undo vsi` roda na visão de sistema: sem linha de contexto
                item["comandos"] = [f"undo vsi {service.vrp_name}"]
            else:
                # o binding mora dentro da interface: contexto + undo
                item["comandos"] = [
                    bloco.comandos[1],
                    f"undo l2 binding vsi {service.vrp_name}",
                ]
            if estado_bloco_vsi(item, recursos) == "consta":
                a_remover.append(item)
        plano.append(changes.PlanoDevice(
            device_id=device_id, blocos=a_remover, baseline_snapshot_id=snap.id,
        ))
    return plano


def valida_pre_checks_vsi(
    session: Session, service: models.VsiService, device: models.Device, recursos: dict,
) -> str | None:
    """§12.2/§9.2 — sessão LDP UP com cada peer, sem binding alheio na Vlanif."""
    peers = _peers(session, service, device.id)
    ldp = recursos.get("mpls_ldp_peer")
    if ldp is None:
        return "Coleta sem 'mpls_ldp_peer' — colete antes de executar (§5.3)."
    for peer in peers:
        achado = next((l for l in ldp if l.get("peer_id") == peer), None)
        if achado is None:
            return f"Par LDP {peer} não listado na coleta do {device.name} (§9.2)."
        if achado.get("estado") is None:
            return (f"Estado do par LDP {peer} desconhecido na coleta do {device.name} — "
                    f"cole e a sessão LDP (§9.2).")
        if achado.get("estado") != "up":
            return f"Par LDP {peer} não está UP na coleta do {device.name} (§9.2)."
    ep = next((e for e in service.endpoints if e.device_id == device.id), None)
    if ep is None:
        return "VSI sem ponta neste equipamento — revalide o serviço."
    for linha in recursos.get("vsi", []) or []:
        if linha.get("name") == service.vrp_name:
            continue
        for ac in linha.get("acs", []) or []:
            if ac.get("interface") == ep.interface:
                return (f"Binding conflitante: {ep.interface} já serve o VSI "
                        f"{linha.get('name')}.")
    return None


def valida_pos_vsi(
    session: Session, service: models.VsiService, snapshot: models.DeviceSnapshot,
) -> list[dict]:
    """Pós-check §13 — VSI, cada pseudowire e o AC da ponta desta coleta."""
    recursos = snapshot.resources or {}
    linhas = [l for l in recursos.get("vsi", []) if l.get("name") == service.vrp_name]
    achado = linhas[0] if linhas else None
    items: list[dict] = []
    if achado is None:
        items.append({
            "tipo": "vsi.ausente", "severidade": "critica",
            "esperado": f"{service.name} ({service.vrp_name})", "encontrado": "não listado",
            "acao": "Verificar a config do VSI (display vsi verbose).",
        })
        return items
    if str(achado.get("estado", "")).lower() != "up":
        items.append({
            "tipo": "vsi.estado", "severidade": "critica",
            "esperado": "up", "encontrado": str(achado.get("estado")),
            "acao": "Verificar LDP, peers e MTU do VSI (§9.3).",
        })
    for peer in achado.get("peers", []) or []:
        if str(peer.get("estado") or "").lower() != "up":
            items.append({
                "tipo": "vsi.peer", "severidade": "critica",
                "esperado": "up", "encontrado": f"{peer.get('peer')}: {peer.get('estado')}",
                "acao": "Conferir o pseudowire e a sessão LDP com o outro PE (§9.3).",
            })
    ep = next((e for e in service.endpoints if e.device_id == snapshot.device_id), None)
    if ep is not None:
        for ac in achado.get("acs", []) or []:
            if ac.get("interface") != ep.interface:
                continue
            if str(ac.get("estado") or "").lower() != "up":
                items.append({
                    "tipo": "vsi.ac", "severidade": "atencao",
                    "esperado": "up", "encontrado": str(ac.get("estado")),
                    "acao": "Conferir o l2 binding e a Vlanif desta ponta.",
                })
    if achado.get("mtu") is not None and int(achado["mtu"]) != service.mtu:
        items.append({
            "tipo": "vsi.mtu", "severidade": "atencao",
            "esperado": str(service.mtu), "encontrado": str(achado["mtu"]),
            "acao": "Conferir o mtu do VSI e reaplicar (§9.3).",
        })
    return items
```

- [ ] **Step 5: Rodar os testes do render**

Run: `uv run pytest tests/automation/test_vsi.py -q`
Expected: PASS.

- [ ] **Step 6: Rodar a suíte de automação e o lint**

Run: `uv run pytest tests/automation -q && uv run ruff check src tests`
Expected: PASS e `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/automation/templates/huawei_vrp/vsi.j2 \
        src/gerenet/automation/templates/huawei_vrp/vsi_ac.j2 \
        src/gerenet/automation/vsi.py tests/automation/test_vsi.py
git commit -m "feat(vsi): render, planos e pré/pós-checks do VSI multiponto"
```

---

### Task 4: Change request de escopo `vsi`

**Files:**
- Modify: `src/gerenet/domain/services/change_requests.py` (`_RECONCILIA_INDISPONIVEL`, `_ROLLBACK_INDISPONIVEL`, `_exige_vsi_ativo`, `_create_vsi`, `_replaneja`, `gerar_rollback`, `create_change_request`)
- Modify: `src/gerenet/automation/runner.py` (`_CHAVES_POR_ESCOPO`, hooks de pré e pós-check)
- Modify: `src/gerenet/domain/services/mpls.py` (`set_vsi_status`, novo), `src/gerenet/domain/schemas.py` (`VsiStatusIn`), `src/gerenet/api/routers/mpls.py` (PATCH de status)
- Modify: `src/gerenet/cli/mpls.py` (`vsi set-status`)
- Test: `tests/domain/test_change_requests_vsi.py` (novo), `tests/automation/test_runner_vsi.py` (novo), `tests/api/test_mpls_api.py`

**Interfaces:**
- Consumes: `automation.vsi` (Task 3), `mpls.get_vsi` (Task 1).
- Produces: `create_change_request` aceita `escopo="vsi"` com `vsi_id`; `reconciliar` e `gerar_rollback` funcionam para `vsi`; `_CHAVES_POR_ESCOPO["vsi"] == ("interfaces", "vsi", "config_backup")`; o runner chama `valida_pre_checks_vsi` e `valida_pos_vsi` quando o escopo é `vsi`; `set_vsi_status(session, vsi_id, *, admin_status: bool, actor)` com `PATCH /api/v1/mpls/vsi/{id}/status` e `gerenet mpls vsi set-status`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/domain/test_change_requests_vsi.py`:

```python
"""CR de escopo vsi — fase 4, parte 3 (spec §5)."""
import pytest

from gerenet.domain.schemas import (
    ChangeRequestCreate,
    DeviceCreate,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
    VsiCreate,
    VsiEndpointIn,
)
from gerenet.domain.services.change_requests import (
    create_change_request,
    gerar_rollback,
    reconciliar,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, PlanoRollbackVazio, ValidationError
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_vsi, set_vsi_status
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def vsi(db_session):
    site = create_site(db_session, SiteCreate(name="pop-cr-vsi"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.9.4.1", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.9.4.2", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-cr-vsi"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.5.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.5.2"), actor="cli")
    svc = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cr-vsi", vsi_id=800,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=800),
                   VsiEndpointIn(device_id=d2.id, vid=800)],
    ), actor="cli")
    return d1, d2, svc


def _snapshot(db_session, dev, recursos):
    from gerenet.domain import models
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success", resources=recursos,
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def _vsi_coletado(svc, device_id_and_if):
    return [{
        "name": svc.vrp_name, "vsi_id": svc.vsi_id, "estado": "up", "mtu": svc.mtu,
        "peers": [{"peer": "10.255.5.2", "estado": "up"}],
        "acs": [{"interface": interface, "estado": "up"} for interface in device_id_and_if],
    }]


def test_cr_vsi_nasce_com_um_step_por_pe(db_session, vsi):
    d1, d2, svc = vsi
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, acao="provision", motivo="Ativar VSI do cliente.",
    ), ator_id=None)
    assert cr.escopo == "vsi"
    assert cr.vsi_id == svc.id
    assert cr.circuit_id is None and cr.l2vc_id is None
    assert {s.device_id for s in cr.steps} == {d1.id, d2.id}
    assert cr.status == "rascunho"


def test_cr_vsi_exige_vsi_id_e_servico_ativo(db_session, vsi):
    _, _, svc = vsi
    with pytest.raises(Exception):
        ChangeRequestCreate(escopo="vsi", motivo="sem id")
    set_vsi_status(db_session, svc.id, admin_status=False, actor="cli")
    with pytest.raises(ConflictError):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="vsi", vsi_id=svc.id, motivo="desativado",
        ), ator_id=None)


def test_reconciliar_vsi_recomputa_ponta_pendente(db_session, vsi):
    d1, d2, svc = vsi
    # coleta SEM o serviço: com o VSI já no encontrado o plano sai vazio (skip por
    # presença) e não haveria o que replanejar — é o que este teste quer exercitar
    vazio = {"vsi": [], "interfaces": [], "config_backup": ""}
    _snapshot(db_session, d1, vazio)
    _snapshot(db_session, d2, vazio)
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, motivo="ativar",
    ), ator_id=None)
    cr.status = "erro"
    for step in cr.steps:
        step.status = "aplicado" if step.device_id == d1.id else "falhou"
    db_session.commit()
    cr = reconciliar(db_session, cr.id, actor="cli")
    assert cr.status == "aguardando_aprovacao"
    pendente = next(s for s in cr.steps if s.device_id == d2.id)
    assert pendente.status == "pendente" and pendente.plano_json


def test_rollback_vsi_provision_gera_filho_remove(db_session, vsi):
    d1, d2, svc = vsi
    _snapshot(db_session, d1, {"vsi": _vsi_coletado(svc, ["Vlanif800"]),
                               "interfaces": [], "config_backup": ""})
    _snapshot(db_session, d2, {"vsi": _vsi_coletado(svc, ["Vlanif800"]),
                               "interfaces": [], "config_backup": ""})
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, motivo="ativar",
    ), ator_id=None)
    cr.status = "aplicado"
    for step in cr.steps:
        step.status = "aplicado"
    db_session.commit()
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
    assert filho.escopo == "vsi" and filho.vsi_id == svc.id
    assert filho.acao == "remove" and filho.rollback_de == cr.id
    assert filho.status == "aguardando_aprovacao"
    comandos = [c for s in filho.steps for b in s.plano_json for c in b["comandos"]]
    assert comandos.count(f"undo vsi {svc.vrp_name}") == 2
    assert comandos.count(f"undo l2 binding vsi {svc.vrp_name}") == 2


def test_rollback_vsi_sem_encontrado_eh_plano_vazio(db_session, vsi):
    d1, d2, svc = vsi
    vazio = {"vsi": [], "interfaces": [], "config_backup": ""}
    _snapshot(db_session, d1, vazio)
    _snapshot(db_session, d2, vazio)
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, motivo="ativar",
    ), ator_id=None)
    cr.status = "aplicado"
    for step in cr.steps:
        step.status = "aplicado"
    db_session.commit()
    del cr  # o objeto antigo não importa: o serviço recarrega pelo id
    with pytest.raises(PlanoRollbackVazio):
        gerar_rollback(db_session, cr_id=1, ator_id=None, actor="cli")


def test_cr_vsi_desativado_nao_replaneja(db_session, vsi):
    """Serviço desativado não recebe mudanças na reconciliação (§5)."""
    d1, d2, svc = vsi
    _snapshot(db_session, d1, {"vsi": [], "interfaces": [], "config_backup": ""})
    _snapshot(db_session, d2, {"vsi": [], "interfaces": [], "config_backup": ""})
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, motivo="ativar",
    ), ator_id=None)
    cr.status = "erro"
    db_session.commit()
    set_vsi_status(db_session, svc.id, admin_status=False, actor="cli")
    with pytest.raises(ConflictError):
        reconciliar(db_session, cr.id, actor="cli")
```

Nota: se `test_rollback_vsi_sem_encontrado_eh_plano_vazio` ficar confuso com o id fixo, capture o id em `cr_id = cr.id` antes do `del` e use `gerar_rollback(db_session, cr_id, ...)`.

- [ ] **Step 2: Escrever o teste do runner**

Crie `tests/automation/test_runner_vsi.py` no molde de `tests/automation/test_runner_l2vc.py` (mesmo padrão de fake de coleta): um teste afirmando que o gate de recursos do escopo `vsi` exige `("interfaces", "vsi", "config_backup")` e um afirmando que o pré-check do VSI bloqueia quando o par LDP não está UP. Use `_CHAVES_POR_ESCOPO["vsi"]` diretamente para o primeiro:

```python
def test_gate_de_recursos_do_escopo_vsi() -> None:
    from gerenet.automation.runner import _CHAVES_POR_ESCOPO, _chaves_incompletas
    assert _CHAVES_POR_ESCOPO["vsi"] == ("interfaces", "vsi", "config_backup")
    assert _chaves_incompletas({"interfaces": [], "config_backup": ""}, {}, "vsi") == ["vsi"]
```

- [ ] **Step 3: Rodar e confirmar que falham**

Run: `uv run pytest tests/domain/test_change_requests_vsi.py tests/automation/test_runner_vsi.py -q`
Expected: FAIL — sem `vsi_id` no serviço, o `create_change_request` cai no caminho de circuito e levanta `NotFoundError`.

- [ ] **Step 4: Liberar o escopo no serviço**

Em `src/gerenet/domain/services/change_requests.py`:

1. remova as chaves `"vsi"` dos dois dicionários `_RECONCILIA_INDISPONIVEL` e `_ROLLBACK_INDISPONIVEL` (ficam vazios: escreva-os como `{}` e ajuste o comentário acima para registrar que o último escopo bloqueado saiu nesta frente);
2. acrescente o guard ao lado do `_exige_l2vc_ativo`:

```python
def _exige_vsi_ativo(svc: models.VsiService) -> None:
    """Serviço e domínio ativos — desativado não recebe mudanças (§14.1)."""
    if not svc.admin_status:
        raise ConflictError("VSI desativado não recebe mudanças.")
    dom = svc.domain
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe mudanças.")
```

3. em `create_change_request`, antes do caminho do circuito:

```python
    if data.escopo == "vsi":
        return _create_vsi(session, data, ator_id=ator_id, actor=actor)
```

4. acrescente `_create_vsi` copiando a estrutura de `_create_l2vc`:

```python
def _create_vsi(
    session: Session, data: schemas.ChangeRequestCreate, *, ator_id: int | None = None, actor: str = "cli",
) -> models.ChangeRequest:
    """CR de VSI multiponto — um step por PE, plano na criação (§9.3)."""
    from gerenet.automation import vsi as vsi_auto
    from gerenet.domain.services.mpls import get_vsi

    servico = get_vsi(session, data.vsi_id)
    _exige_vsi_ativo(servico)
    if len(servico.endpoints) < 2:
        raise ValidationError("VSI com menos de duas pontas não tem o que provisionar.")
    plano = (
        vsi_auto.plan_provision_vsi(session, servico)
        if data.acao == "provision"
        else vsi_auto.plan_remocao_vsi(session, servico)
    )
    cr = models.ChangeRequest(
        circuit_id=None, vsi_id=servico.id, acao=data.acao, criticidade=data.criticidade,
        motivo=data.motivo, ticket=data.ticket, solicitante_id=ator_id, status="rascunho",
        escopo="vsi",
    )
    session.add(cr)
    session.flush()
    _cria_steps(session, cr, plano)
    if not cr.steps or all(not s.plano_json for s in cr.steps):
        raise PlanoVazio("VSI sem blocos a aplicar — revalide o serviço e a coleta.")
    registrar(
        session, tipo="change.created", ator=actor, objeto="change_request",
        objeto_id=cr.id, antes=None,
        depois={"vsi_id": servico.id, "acao": cr.acao, "criticidade": cr.criticidade,
                "steps": len(cr.steps), "blocos": sum(len(s.plano_json) for s in cr.steps)},
    )
    session.commit()
    session.refresh(cr)
    return cr
```

5. no `_replaneja`, depois do ramo `l2vc`:

```python
    if cr.escopo == "vsi":
        from gerenet.automation import vsi as vsi_auto
        from gerenet.domain.services.mpls import get_vsi

        svc = get_vsi(session, cr.vsi_id)
        _exige_vsi_ativo(svc)
        plano = (
            vsi_auto.plan_provision_vsi(session, svc)
            if acao == "provision"
            else vsi_auto.plan_remocao_vsi(session, svc)
        )
        for item in plano:
            if item.device_id == device_id:
                return item
        return changes.PlanoDevice(device_id=device_id, blocos=[], baseline_snapshot_id=None)
```

6. no `gerar_rollback`, entre o ramo `l2vc` e o `else` do circuito:

```python
    elif cr.escopo == "vsi":
        _exige_vsi_ativo(get_vsi(session, cr.vsi_id))
        filho = models.ChangeRequest(
            circuit_id=None, vsi_id=cr.vsi_id, escopo="vsi",
            acao="remove" if cr.acao == "provision" else "provision",
            criticidade=cr.criticidade, motivo=f"Rollback do CR #{cr.id}",
            solicitante_id=ator_id, status="aguardando_aprovacao", rollback_de=cr.id,
        )
```

E, no laço dos steps, estenda o ramo que hoje atende o `l2vc` para atender os dois escopos:

```python
        if cr.escopo in ("l2vc", "vsi"):
            item = _replaneja(session, cr, step.device_id, acao=filho.acao)
            if not item.blocos:
                continue
            session.add(models.ChangeStep(
                change_request_id=filho.id, device_id=step.device_id, status="pendente",
                plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
                aviso=item.aviso,
            ))
            continue
```

(importe `get_vsi` de `gerenet.domain.services.mpls` no topo ou dentro das funções, seguindo o padrão dos outros ramos).

7. acrescente o status do VSI, que o produto ainda não tinha (sem ele o guard de serviço desativado fica inalcançável e o operador não consegue desligar um VSI). Em `src/gerenet/domain/services/mpls.py`, ao lado de `set_l2vc_status`:

```python
def set_vsi_status(session: Session, vsi_id: int, *, admin_status: bool, actor: str = "cli") -> models.VsiService:
    svc = _vsi(session, vsi_id)
    antes, svc.admin_status = svc.admin_status, admin_status
    session.flush()
    registrar(session, tipo="mpls.vsi.status", ator=actor, objeto="vsi", objeto_id=svc.id,
              antes={"admin_status": antes}, depois={"admin_status": admin_status})
    session.commit()
    return _vsi(session, svc.id)
```

Em `src/gerenet/domain/schemas.py`, ao lado de `L2vcStatusIn`:

```python
class VsiStatusIn(BaseModel):
    admin_status: bool
```

Em `src/gerenet/api/routers/mpls.py`, espelhando o PATCH do L2VC:

```python
@router.patch("/vsi/{vsi_id}/status", response_model=VsiOut)
def set_vsi_status(
    vsi_id: int,
    data: VsiStatusIn,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    try:
        return svc.out_vsi(
            svc.set_vsi_status(session, vsi_id, admin_status=data.admin_status, actor=actor.nome)
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

Em `src/gerenet/cli/mpls.py`, um `vsi set-status` no molde do `l2vc set-status` (parâmetro `--admin-status/--no-admin-status` e eco do resultado), e um teste de API em `tests/api/test_mpls_api.py` cobrindo o PATCH (200 no caminho feliz, 404 em id inexistente).

8. exponha o nome do VSI na CR, que é o que a web usa para rotular o objeto (o mesmo padrão do `l2vc_name`): em `src/gerenet/domain/models.py`, ao lado das propriedades `l2vc_name`/`upstream_name` do `ChangeRequest`:

```python
    @property
    def vsi_name(self) -> str | None:
        return self.vsi.name if self.vsi is not None else None
```

(se o `ChangeRequest` não tiver uma relationship `vsi`, acrescente `vsi: Mapped["VsiService | None"] = relationship()` junto das outras). Em `src/gerenet/domain/schemas.py`, no `ChangeRequestOut`, ao lado de `l2vc_id`/`l2vc_name`:

```python
    vsi_id: int | None = None
    vsi_name: str | None = None  # espelho do modelo (propriedade vsi_name)
```

Com testes: a API `GET /change-requests/{id}` de uma CR de escopo `vsi` devolve `vsi_id` e `vsi_name` preenchidos.

- [ ] **Step 5: Ligar o runner**

Em `src/gerenet/automation/runner.py`:

1. `_CHAVES_POR_ESCOPO` ganha a linha `"vsi": ("interfaces", "vsi", "config_backup"),`;
2. nos pontos em que o runner chama `valida_pre_checks_l2vc` e `valida_pos_l2vc` (setup e pós-check do step, ambos condicionados por `cr.escopo`), acrescente o ramo equivalente para `vsi`, chamando `vsi_auto.valida_pre_checks_vsi(session, svc, dev, recursos)` e `vsi_auto.valida_pos_vsi(session, svc, snapshot)`, com `get_vsi(session, cr.vsi_id)` resolvendo o serviço.

- [ ] **Step 6: Rodar os testes**

Run: `uv run pytest tests/domain/test_change_requests_vsi.py tests/automation/test_runner_vsi.py tests/domain/test_change_requests_l2vc.py tests/api -q`
Expected: PASS. Se algum teste de API afirmar que o escopo `vsi` é barrado, atualize-o para o comportamento novo (mesmo movimento da frente do L2VC).

- [ ] **Step 7: Rodar a suíte completa de Python e o lint**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: PASS e `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/domain/services/change_requests.py src/gerenet/domain/services/mpls.py \
        src/gerenet/domain/schemas.py src/gerenet/automation/runner.py \
        src/gerenet/api/routers/change_requests.py src/gerenet/api/routers/mpls.py \
        src/gerenet/cli/mpls.py tests/domain/test_change_requests_vsi.py \
        tests/automation/test_runner_vsi.py tests/api/test_mpls_api.py
git commit -m "feat(vsi): change request de escopo vsi, rollback, reconciliação e status"
```

---

### Task 5: Web e CLI

**Files:**
- Modify: `web/src/pages/MplsVsiDetail.tsx`, `web/src/pages/MplsVsi.tsx`
- Modify: `web/src/api/types.ts`, `web/src/api/hooks.ts` (se o tipo do VSI mudar)
- Modify: `web/src/pages/ChangeRequestDetail.tsx` (`escopoComFluxo` inclui `vsi`)
- Modify: `src/gerenet/cli/mpls.py` (`vsi add`)
- Test: `web/src/pages/MplsVsiDetail.test.tsx` (novo ou ampliado), `web/src/pages/ChangeRequestDetail.test.tsx`, `tests/cli/test_cli_smoke.py`

**Interfaces:**
- Consumes: `VsiOut.endpoints` (Task 1), CR de escopo `vsi` (Task 4).
- Produces: detalhe do VSI com ACs e estado; botão "Solicitar mudança" para CR de escopo `vsi`; `gerenet mpls vsi add --endpoint DEVICE_ID:VID` repetível e `--flow-label`.

- [ ] **Step 1: Escrever os testes que falham**

Em `web/src/pages/ChangeRequestDetail.test.tsx`, acrescente:

```tsx
  it("mostra Gerar rollback numa CR de escopo vsi aplicada", async () => {
    crAtual = {
      ...crDe(2, "aplicado"),
      circuit_id: null, escopo: "vsi", l2vc_id: null, l2vc_name: null,
      upstream_id: null, upstream_name: "vsi-cliente", vsi_id: 3, vsi_name: "vsi-cliente",
    } as typeof crAtual;
    renderDetail();
    await screen.findByText("Change request #1");
    expect(screen.getByRole("button", { name: "Gerar rollback" })).toBeInTheDocument();
  });
```

Se o tipo `ChangeRequestOut` do front ainda não tiver `vsi_id`/`vsi_name`, acrescente os dois campos em `web/src/api/types.ts` antes (o backend passa a devolvê-los na Task 4).

Em `web/src/pages/MplsVsiDetail.test.tsx`, cubra: lista de ACs com equipamento, Vlanif e VLAN vindos de `endpoints`, e o botão "Solicitar mudança" que navega para a criação de CR com `escopo: "vsi"`.

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd web && npx vitest run src/pages/ChangeRequestDetail.test.tsx src/pages/MplsVsiDetail.test.tsx`
Expected: FAIL — `escopoComFluxo` ainda devolve `false` para `vsi` e a página do VSI ainda lê `members`.

- [ ] **Step 3: Ajustar a web**

1. `ChangeRequestDetail.tsx`: `escopoComFluxo` passa a devolver `true` também para `"vsi"`, e o comentário acima registra que todos os escopos agora têm o fluxo;
2. `MplsVsiDetail.tsx`: trocar a leitura de `members` por `endpoints` e mostrar a tabela de ACs (equipamento, Vlanif, VLAN, estado) mais o estado por pseudowire da última coleta quando disponível; incluir o botão "Solicitar mudança" (mesmo padrão do detalhe do L2VC);
3. `web/src/api/types.ts` e `hooks.ts`: `VsiOut.members` → `VsiOut.endpoints`, mais `flow_label`, `description`, e `vsi_id`/`vsi_name` no `ChangeRequestOut`.

- [ ] **Step 4: Ajustar a CLI**

Em `src/gerenet/cli/mpls.py`, o comando `vsi add` passa a aceitar endpoints:

```python
@endpoint_app.command("add")
def vsi_add(
    domain_id: int = typer.Option(..., "--domain-id"),
    name: str = typer.Option(..., "--name"),
    vsi_id: int | None = typer.Option(None, "--vsi-id"),
    endpoint: list[str] = typer.Option([], "--endpoint", help="DEVICE_ID:VID (repetível; VID opcional)"),
    flow_label: bool = typer.Option(False, "--flow-label"),
) -> None:
```

Converta cada `--endpoint` em `VsiEndpointIn` (`"3:800"` ou `"3"`) e chame `svc.create_vsi`. Registre no help que o VID omitido assume o VSI-ID.

- [ ] **Step 5: Rodar os testes da web e da CLI**

Run: `cd web && npm run build && npm run test`
Run: `uv run pytest tests/cli tests/api -q`
Expected: PASS nos dois.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/MplsVsiDetail.tsx web/src/pages/MplsVsi.tsx web/src/pages/MplsVsiDetail.test.tsx \
        web/src/pages/ChangeRequestDetail.tsx web/src/pages/ChangeRequestDetail.test.tsx \
        web/src/api/types.ts web/src/api/hooks.ts src/gerenet/cli/mpls.py
git commit -m "feat(web): ACs e mudança controlada no detalhe do VSI"
```

---

### Task 6: Runbook, wiki e estado do repositório

**Files:**
- Modify: `docs/runbook-validacao-switch-mpls.md`
- Modify: `docs/wiki/em-breve/mpls.md`
- Modify: `CLAUDE.md` (seção "Estado do repositório")

**Interfaces:**
- Consumes: o comportamento entregue nas Tasks 1 a 5.
- Produces: documentação alinhada, com a conferência da etapa 1 e o roteiro da etapa 3 para VSI.

- [ ] **Step 1: Atualizar o runbook**

Na etapa 1 (somente leitura), acrescente os dois itens, com o resultado já medido nesta sessão:

```markdown
- [ ] `display current-configuration configuration vsi`: a forma é `vsi <nome> static` com `vsi-id`, `flow-label` e `peer` dentro de `pwsignal ldp`, e `mtu`/`description` no nível do VSI.
- [ ] `display vsi verbose` nos três níveis: `VSI State` do serviço, `Session` de cada peer e `Interface Name`/`State` de cada AC. O `**PW Information` aparece só em alguns VSIs e repete o `Session`, por isso não é parseado.
- [ ] `display current-configuration interface Vlanif<vid>` do AC: confirma o `l2 binding vsi <nome>` e a `description`.
```

Na etapa 3, acrescente o roteiro do VSI de teste: criar o VSI com dois PEs e VID igual ao `vsi_id`, gerar a CR, aprovar, executar e conferir o estado nos três níveis; e a remoção, que desfaz só o binding e o VSI, deixando a `Vlanif` e a `vlan` no equipamento (sobra esperada, visível na divergência).

- [ ] **Step 2: Atualizar a wiki**

Em `docs/wiki/em-breve/mpls.md`, troque a frase que diz que o provisionamento multiponto vem em fase posterior pelo comportamento atual: VSI provisionável com ACs por PE, CR de escopo `vsi` com rollback e reconciliação, pós-check nos três níveis, e a nota de que a `Vlanif` do AC fica no equipamento após a remoção.

- [ ] **Step 3: Atualizar o estado do repositório**

Em `CLAUDE.md`, na seção "Estado do repositório", acrescente um bullet no estilo dos anteriores resumindo: ACs por PE com Vlanif derivada do VID, templates `vsi.j2`/`vsi_ac.j2`, CR de escopo `vsi` com rollback e reconciliação, parser nos três níveis, pós-check `vsi.ausente`/`vsi.estado`/`vsi.peer` (críticos) e `vsi.ac`/`vsi.mtu` (`atencao`), e as dívidas registradas (MAC, `tnl-policy`, limpeza da Vlanif).

- [ ] **Step 4: Rodar os testes que tocam documentação**

Run: `uv run pytest tests/api -q -k wiki`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/runbook-validacao-switch-mpls.md docs/wiki/em-breve/mpls.md CLAUDE.md
git commit -m "docs(fase4): runbook, wiki e estado do repositório do VSI multiponto"
```

---

## Verificação final

- [ ] `uv run pytest -q` — suíte completa verde.
- [ ] `uv run ruff check src tests` — sem avisos.
- [ ] `cd web && npm run build && npm run test` — build e Vitest verdes.
- [ ] Revisar o diff acumulado contra a spec, seção por seção (§3 a §8).
