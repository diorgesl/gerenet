# Automação contínua (Fase 6, parte 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ligar a operação contínua do gerenet: coleta periódica agendada pelo
worker, resumo da divergência gravado em cada coleta, endpoint Prometheus
`/metrics` com os nove itens do §20.1, Grafana no compose de dev e card de
divergências no dashboard.

**Architecture:** O worker passa a rodar com o scheduler nativo do RQ
(`work(with_scheduler=True)`) e arma uma varredura que se reagenda, reusando
`enqueue_collect` inteiro (lock, dedupe e recusas). A coleta grava o resumo do
reconcile no próprio snapshot (`resources["divergencias"]`), e o `/metrics` lê
esse resumo, o banco e o Redis num `Collector` que calcula no scrape, com
registry por aplicação.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 + PostgreSQL, RQ 2.12 (Redis),
Jinja2, `prometheus-client` (dependência nova), React 18 + Vite + Vitest,
Playwright, Prometheus e Grafana no compose de dev.

**Spec:** `docs/superpowers/specs/2026-09-14-gerenet-fase6-automacao-continua-design.md`

## Global Constraints

- Idioma dos artefatos: **português (PT-BR)** — código, comentários, docs, commits.
- **Sem migration**: nada nesta frente muda o schema (o resumo vai em
  `snapshot.resources`, que é JSON). Se um passo pedir Alembic, é sinal de desvio.
- **Dependência nova: só `prometheus-client`** (Task 4), fixada no
  `pyproject.toml` com `uv sync` atualizando o `uv.lock`.
- Testes Python rodam contra o banco **`gerenet_test`** (o conftest trunca a cada
  teste; nunca o banco dev `gerenet`). Postgres e Redis do compose precisam estar
  no ar: `docker compose up -d db redis` (o Redis real é usado pelos testes de
  worker e de métricas).
- Comandos de verificação: `uv run pytest -q`, `uv run ruff check src tests`,
  `cd web && npm run test`, `cd web && npm run build`, `cd web && npm run lint`.
- Os fumos e2e exigem o compose **parado** (porta 8000) e o banco `gerenet_e2e`;
  rodam só na Task 6, e o run-book é `web/e2e/README.md`.
- **Worktree**: esta é a única árvore onde se commita. O hook de isolamento
  recusa comando git composto, então rode `git add`, `git commit` e `git log`
  como comandos simples e separados, sempre da raiz da worktree.
- Commit por task, no padrão do repo (`feat(...)`, `test(...)`, `docs(...)`), em
  PT-BR, terminando com a linha de co-autoria que o harness já injeta.
- Segredo nunca em log, auditoria ou snapshot (§19): o token do `/metrics` entra
  por env e não é impresso em lugar nenhum.

---

## File Structure

**Criados:**

- `tests/worker/test_sweep.py` — varredura e agendamento (Tasks 1 e 2)
- `src/gerenet/api/metrics.py` — collector e rota `/metrics` (Task 4)
- `tests/api/test_metrics.py` — contrato do `/metrics` (Task 4)
- `docker/observability/prometheus.yml` — scrape do `/metrics` (Task 7)
- `docker/observability/grafana/provisioning/datasources/prometheus.yml` (Task 7)
- `docker/observability/grafana/provisioning/dashboards/provider.yml` (Task 7)
- `docker/observability/grafana/dashboards/gerenet.json` (Task 7)
- `docs/runbook-observabilidade.md` (Task 8)

**Modificados:**

- `src/gerenet/config.py` — `collect_interval_minutes` (Task 1), `metrics_token` (Task 4)
- `src/gerenet/worker/tasks.py` — `varredura_coletas`, `armar_varredura`, `worker_main` (Tasks 1 e 2)
- `src/gerenet/automation/runner.py` — `liberta_lock` público (Task 1), resumo da divergência (Task 3)
- `src/gerenet/api/main.py` — chamada de `montar_metrics` (Task 4)
- `src/gerenet/domain/schemas.py` e `src/gerenet/api/dashboard.py` — agregado de divergências (Task 5)
- `tests/automation/test_runner.py` — resumo na coleta (Task 3)
- `tests/api/test_dashboard_api.py` — agregado de divergências (Task 5)
- `web/src/api/types.ts`, `web/src/pages/Dashboard.tsx`, `web/src/pages/Dashboard.test.tsx`, `web/src/styles/global.css`, `web/e2e/smoke.spec.ts` (Task 6)
- `compose.yaml`, `README.md` (Task 7)
- `docs/wiki/equipamentos.md`, `docs/wiki/operacao.md`, `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md`, `CLAUDE.md` (Task 8)

---

### Task 1: Varredura de coletas

**Files:**
- Create: `tests/worker/test_sweep.py`
- Modify: `src/gerenet/config.py` (bloco de settings, depois de `bgp_anomalia_pct`)
- Modify: `src/gerenet/worker/tasks.py` (imports e função nova no fim do arquivo)
- Modify: `src/gerenet/automation/runner.py:59,220,925,962` (renomear `_liberta_lock` → `liberta_lock`)

**Interfaces:**
- Consumes: `enqueue_collect(device_id, *, actor, origin)` (worker/tasks.py),
  `get_settings()`, `get_session()`, `_redis(settings)`, `Settings.lock_ttl_seconds`.
- Produces: `varredura_coletas(agora: datetime | None = None) -> dict` e a
  constante `SWEEP_LOCK = "gerenet:lock:sweep"` em `gerenet.worker.tasks`;
  `Settings.collect_interval_minutes: int`; `liberta_lock(redis, chave_lock,
  token)` em `gerenet.automation.runner`. Retorno de `varredura_coletas`:
  `{"status": "ok"|"skipped", "message"?: str, "enfileirados"?: int,
  "pulados_idade"?: int, "recusados"?: list[dict]}`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/worker/test_sweep.py` com o conteúdo abaixo (o fixture limpa a fila,
o registry de agendados e o lock, no padrão de `tests/worker/test_tasks.py`, que
usa Redis real):

```python
"""Varredura de coletas (Fase 6, parte 1): o que a coleta periódica enfileira.

Redis real, o mesmo dos testes de `tasks`: a varredura usa lock e fila de
verdade. A limpeza cobre a fila `gerenet-collect`, o registry de agendados e o
lock da varredura.
"""
from datetime import UTC, datetime, timedelta

import pytest
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from gerenet.config import Settings, set_settings
from gerenet.domain.models import AuditEvent, CredentialGroup, DeviceSnapshot
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device
from gerenet.worker.tasks import SWEEP_LOCK, enqueue_collect, varredura_coletas

CHAVE_AGENDADOS = "rq:scheduled:gerenet-collect"


@pytest.fixture()
def fila_limpa() -> Redis:
    r = Redis.from_url(Settings(_env_file=None).redis_url)
    fila = Queue("gerenet-collect", connection=r)
    fila.empty()
    r.delete(CHAVE_AGENDADOS, SWEEP_LOCK)
    yield r
    fila.empty()
    r.delete(CHAVE_AGENDADOS, SWEEP_LOCK)


def _grupo(db_session: Session) -> CredentialGroup:
    grupo = CredentialGroup(
        name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao"
    )
    db_session.add(grupo)
    db_session.commit()
    return grupo


def _dev(
    db_session: Session,
    nome: str,
    endereco: str,
    *,
    grupo: CredentialGroup | None,
    ativo: bool = True,
):
    dev = create_device(
        db_session,
        DeviceCreate(
            name=nome,
            management_address=endereco,
            credential_group_id=grupo.id if grupo is not None else None,
        ),
        actor="cli",
    )
    if not ativo:
        dev.admin_status = False
        db_session.commit()
    return dev


def _com_snapshot(db_session: Session, dev, *, minutos_atras: int) -> None:
    db_session.add(
        DeviceSnapshot(
            device_id=dev.id,
            status="success",
            resources={},
            started_at=datetime.now(UTC) - timedelta(minutes=minutos_atras),
        )
    )
    db_session.commit()


def test_varredura_enfileira_so_ativos_com_credencial(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    alvo = _dev(db_session, "com-credencial", "10.10.0.1", grupo=grupo)
    _dev(db_session, "sem-credencial", "10.10.0.2", grupo=None)
    _dev(db_session, "desativado", "10.10.0.3", grupo=grupo, ativo=False)

    resultado = varredura_coletas()

    assert resultado["status"] == "ok"
    assert resultado["enfileirados"] == 1
    assert resultado["pulados_idade"] == 0
    assert resultado["recusados"] == []
    jobs = list(Queue("gerenet-collect", connection=fila_limpa).get_jobs())
    assert [job.args[0] for job in jobs] == [alvo.id]
    assert jobs[0].meta["origin"] == "scheduler"

    evento = db_session.query(AuditEvent).filter_by(type="collect.sweep").one()
    assert evento.actor == "scheduler"
    assert evento.details["enfileirados"] == 1
    assert evento.details["pulados_idade"] == 0
    assert evento.details["recusados"] == []


def test_varredura_pula_coletado_dentro_do_intervalo(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    dev = _dev(db_session, "coletado-agora", "10.10.1.1", grupo=grupo)
    _com_snapshot(db_session, dev, minutos_atras=5)

    resultado = varredura_coletas()

    assert resultado["pulados_idade"] == 1
    assert resultado["enfileirados"] == 0
    assert Queue("gerenet-collect", connection=fila_limpa).count == 0


def test_varredura_enfileira_quem_esta_fora_do_intervalo(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    dev = _dev(db_session, "coletado-ha-tempo", "10.10.1.2", grupo=grupo)
    _com_snapshot(db_session, dev, minutos_atras=120)

    resultado = varredura_coletas()

    assert resultado["pulados_idade"] == 0
    assert resultado["enfileirados"] == 1


def test_varredura_conta_recusa_do_enqueue(fila_limpa: Redis, db_session: Session) -> None:
    """Coleta já pendente não entra de novo: a recusa do enqueue vira `recusados`."""
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    dev = _dev(db_session, "ja-na-fila", "10.10.1.3", grupo=grupo)
    enqueue_collect(dev.id, actor="cli", origin="cli")

    resultado = varredura_coletas()

    assert resultado["enfileirados"] == 0
    assert resultado["recusados"][0]["device"] == "ja-na-fila"
    assert "pendente" in resultado["recusados"][0]["motivo"]


def test_varredura_desligada_nao_faz_nada(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=0))
    grupo = _grupo(db_session)
    _dev(db_session, "ativo", "10.10.2.1", grupo=grupo)

    resultado = varredura_coletas()

    assert resultado == {"status": "skipped", "message": "Coleta periódica desligada."}
    assert Queue("gerenet-collect", connection=fila_limpa).count == 0
    assert db_session.query(AuditEvent).filter_by(type="collect.sweep").count() == 0


def test_varredura_com_lock_tomado_nao_enfileira(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    _dev(db_session, "ativo", "10.10.3.1", grupo=grupo)
    fila_limpa.set(SWEEP_LOCK, "outra-varredura")

    resultado = varredura_coletas()

    assert resultado == {"status": "skipped", "message": "Varredura já em andamento."}
    assert Queue("gerenet-collect", connection=fila_limpa).count == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/worker/test_sweep.py -q`
Expected: FAIL no import — `ImportError: cannot import name 'SWEEP_LOCK' from 'gerenet.worker.tasks'`.

- [ ] **Step 3: Adicionar o setting**

Em `src/gerenet/config.py`, logo depois do bloco do B5 (`bgp_anomalia_pct`):

```python
    # F6: coleta periódica no worker (varredura). 0 = desligada; ligar é decisão
    # explícita de quem instala, e mudar o valor pede restart do worker (o arm
    # da varredura acontece na subida).
    collect_interval_minutes: int = 0
```

- [ ] **Step 4: Tornar o helper de lock público**

Em `src/gerenet/automation/runner.py`, renomeie a definição e as três chamadas
(`grep -n "_liberta_lock" src/gerenet/automation/runner.py` lista as linhas 59,
220, 925 e 962):

```bash
# troca as 4 ocorrências, sem tocar no corpo da função
python - <<'PY'
from pathlib import Path
p = Path("src/gerenet/automation/runner.py")
texto = p.read_text(encoding="utf-8")
assert texto.count("_liberta_lock") == 4, texto.count("_liberta_lock")
p.write_text(texto.replace("_liberta_lock", "liberta_lock"), encoding="utf-8")
PY
```

- [ ] **Step 5: Implementar a varredura**

Em `src/gerenet/worker/tasks.py`, ajuste os imports do topo para:

```python
import secrets
from datetime import UTC, datetime, timedelta

from redis import Redis
from rq import Queue, get_current_job
from sqlalchemy import select

from gerenet.automation.runner import liberta_lock, run_change, run_collection
from gerenet.config import Settings, get_settings
from gerenet.db import get_session
from gerenet.domain import models
from gerenet.domain.services import change_requests as change_svc
from gerenet.domain.services import devices as device_svc
from gerenet.domain.services.errors import NotFoundError

SWEEP_LOCK = "gerenet:lock:sweep"
```

E acrescente, depois de `change_task` e antes de `worker_main`:

```python
def varredura_coletas(agora: datetime | None = None) -> dict:
    """Enfileira a coleta dos equipamentos ativos com credencial (§10, F6).

    Chamada pelo agendador do worker (e pelos testes). Não levanta por recusa:
    quem não entra na fila (coleta em andamento, job pendente, equipamento
    desativado desde a consulta) conta em `recusados` e fica auditado. O lock
    `gerenet:lock:sweep` impede duas varreduras sobrepostas.
    """
    settings = get_settings()
    if settings.collect_interval_minutes <= 0:
        return {"status": "skipped", "message": "Coleta periódica desligada."}

    agora = agora or datetime.now(UTC)
    limite = agora - timedelta(minutes=settings.collect_interval_minutes)
    r = _redis(settings)
    token = secrets.token_hex(16)
    try:
        if not r.set(SWEEP_LOCK, token, nx=True, ex=settings.lock_ttl_seconds):
            return {"status": "skipped", "message": "Varredura já em andamento."}
        enfileirados: list[str] = []
        recusados: list[dict] = []
        pulados_idade = 0
        with get_session() as session:
            devices = list(
                session.scalars(
                    select(models.Device)
                    .where(
                        models.Device.admin_status.is_(True),
                        models.Device.credential_group_id.isnot(None),
                    )
                    .order_by(models.Device.name)
                )
            )
            for dev in devices:
                ultimo = session.scalar(
                    select(models.DeviceSnapshot.started_at)
                    .where(models.DeviceSnapshot.device_id == dev.id)
                    .order_by(models.DeviceSnapshot.id.desc())
                    .limit(1)
                )
                if ultimo is not None and ultimo > limite:
                    pulados_idade += 1
                    continue
                enfileirado = enqueue_collect(dev.id, actor="scheduler", origin="scheduler")
                if enfileirado["queued"]:
                    enfileirados.append(dev.name)
                else:
                    recusados.append({"device": dev.name, "motivo": enfileirado["message"]})
            session.add(
                models.AuditEvent(
                    type="collect.sweep",
                    actor="scheduler",
                    details={
                        "enfileirados": len(enfileirados),
                        "pulados_idade": pulados_idade,
                        "recusados": recusados,
                    },
                )
            )
        return {
            "status": "ok",
            "enfileirados": len(enfileirados),
            "pulados_idade": pulados_idade,
            "recusados": recusados,
        }
    finally:
        liberta_lock(r, SWEEP_LOCK, token)
        r.close()
```

- [ ] **Step 6: Rodar os testes**

Run: `uv run pytest tests/worker/test_sweep.py -q`
Expected: PASS (6 testes).

Depois rode a suíte de worker inteira, porque o rename do lock toca o runner:
`uv run pytest tests/worker tests/automation -q` → PASS.

- [ ] **Step 7: Lint e commit**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

```bash
git add src/gerenet/config.py src/gerenet/worker/tasks.py src/gerenet/automation/runner.py tests/worker/test_sweep.py
git commit -m "feat(worker): varredura de coletas do intervalo configurado"
```

---

### Task 2: Agendamento da varredura no worker

**Files:**
- Modify: `src/gerenet/worker/tasks.py` (arm, reagendamento dentro da varredura, `worker_main`)
- Modify: `tests/worker/test_sweep.py` (testes de agendamento)

**Interfaces:**
- Consumes: `varredura_coletas`, `SWEEP_LOCK` (Task 1).
- Produces: `armar_varredura(r: Redis, settings: Settings | None = None) -> bool`
  e `SWEEP_JOB_TIMEOUT = 600` em `gerenet.worker.tasks`. `worker_main` passa a
  rodar com scheduler embutido e a armar a varredura na subida.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/worker/test_sweep.py`, com os imports
`from rq import Job, Queue` (já está) e
`from gerenet.worker.tasks import armar_varredura`:

```python
def test_armar_sem_intervalo_nao_agenda(fila_limpa: Redis) -> None:
    armar = armar_varredura(fila_limpa, Settings(_env_file=None, collect_interval_minutes=0))
    assert armar is False
    assert fila_limpa.zcard(CHAVE_AGENDADOS) == 0


def test_armar_e_idempotente(fila_limpa: Redis) -> None:
    settings = Settings(_env_file=None, collect_interval_minutes=30)

    assert armar_varredura(fila_limpa, settings) is True
    assert armar_varredura(fila_limpa, settings) is False

    fila = Queue("gerenet-collect", connection=fila_limpa)
    assert len(fila.scheduled_job_registry.get_job_ids()) == 1


def test_varredura_reagenda_a_proxima(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=30))
    grupo = _grupo(db_session)
    _dev(db_session, "ativo", "10.11.0.1", grupo=grupo)

    varredura_coletas()

    fila = Queue("gerenet-collect", connection=fila_limpa)
    agendados = fila.scheduled_job_registry.get_job_ids()
    assert len(agendados) == 1
    assert Job.fetch(agendados[0], connection=fila_limpa).func_name.endswith(".varredura_coletas")


def test_varredura_desligada_nao_reagenda(fila_limpa: Redis) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=0))

    varredura_coletas()

    assert fila_limpa.zcard(CHAVE_AGENDADOS) == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/worker/test_sweep.py -q -k "armar or reagenda"`
Expected: FAIL — `ImportError: cannot import name 'armar_varredura'`.

- [ ] **Step 3: Implementar o arm e o reagendamento**

Em `src/gerenet/worker/tasks.py`, acrescente a constante ao lado de
`SWEEP_LOCK`:

```python
SWEEP_JOB_TIMEOUT = 600
```

Acrescente `armar_varredura` logo antes de `varredura_coletas`:

```python
def armar_varredura(r: Redis, settings: Settings | None = None) -> bool:
    """Agenda a varredura, se a coleta periódica está ligada e nenhuma está agendada.

    Idempotente de propósito: o worker chama na subida, então uma agenda perdida
    no Redis volta no próximo boot sem duplicar job.
    """
    settings = settings or get_settings()
    if settings.collect_interval_minutes <= 0:
        return False
    fila = Queue("gerenet-collect", connection=r)
    alvo = f"{varredura_coletas.__module__}.{varredura_coletas.__name__}"
    for job_id in fila.scheduled_job_registry.get_job_ids():
        job = Job.fetch(job_id, connection=r)
        if job is not None and job.func_name == alvo:
            return False
    fila.enqueue_in(
        timedelta(minutes=settings.collect_interval_minutes),
        varredura_coletas,
        job_timeout=SWEEP_JOB_TIMEOUT,
    )
    return True
```

No import do `rq`, inclua `Job`:

```python
from rq import Job, Queue, get_current_job
```

E, dentro de `varredura_coletas`, imediatamente antes do `return {"status": "ok", ...}`,
o reagendamento (releitura do intervalo: desligar vale já na execução seguinte):

```python
        settings = get_settings()
        if settings.collect_interval_minutes > 0:
            Queue("gerenet-collect", connection=r).enqueue_in(
                timedelta(minutes=settings.collect_interval_minutes),
                varredura_coletas,
                job_timeout=SWEEP_JOB_TIMEOUT,
            )
```

- [ ] **Step 4: Ligar o scheduler no worker**

Substitua `worker_main` inteiro por:

```python
def worker_main() -> None:
    from rq.worker import Worker

    settings = get_settings()
    with _redis(settings) as r:
        armar_varredura(r, settings)
        Worker(["gerenet-collect", "gerenet-change"], connection=r).work(with_scheduler=True)
```

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/worker/test_sweep.py -q`
Expected: PASS (10 testes).

- [ ] **Step 6: Conferir o arm no boot do worker**

Suba um worker da worktree com intervalo ligado, confira que ele armou a
varredura no Redis e derrube o processo. Nada é executado (a varredura só vence
em 60 min) e o worker do compose não é tocado:

Run:
```bash
GERENET_COLLECT_INTERVAL_MINUTES=60 uv run gerenet-worker > /tmp/gerenet-worker-smoke.log 2>&1 &
WORKER_PID=$!
sleep 6
uv run python -c "
from redis import Redis
from rq import Job, Queue
from gerenet.config import Settings
r = Redis.from_url(Settings(_env_file=None).redis_url)
ids = Queue('gerenet-collect', connection=r).scheduled_job_registry.get_job_ids()
print('agendados:', len(ids))
print('func:', Job.fetch(ids[0], connection=r).func_name if ids else '-')
"
kill $WORKER_PID
```
Expected: `agendados: 1` e `func: gerenet.worker.tasks.varredura_coletas`.
Confirme também que o worker subiu com o scheduler no log:
`grep -i "scheduler" /tmp/gerenet-worker-smoke.log` deve mostrar a linha do RQ
(`Scheduler for ... started`).

- [ ] **Step 7: Lint e commit**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

```bash
git add src/gerenet/worker/tasks.py tests/worker/test_sweep.py
git commit -m "feat(worker): agendamento da varredura no boot e reagendamento ao fim"
```

---

### Task 3: Resumo da divergência gravado na coleta

**Files:**
- Modify: `src/gerenet/automation/runner.py` (chamada em `run_collection`, depois de `sincronizar_mpls`; helper novo antes de `run_collection`)
- Modify: `tests/automation/test_runner.py` (3 testes novos no fim)

**Interfaces:**
- Consumes: `reconciliar_device(session, device_id, *, snapshot_id=None) -> ReconcileResult`
  (`ReconcileResult.items: list[ReconcileItem]` com `severidade` em
  `critica|atencao|aviso|alerta`, e `ReconcileResult.aviso: str | None`).
- Produces: `_resumo_divergencias(session, device_id, snapshot_id, actor) -> dict | None`
  em `gerenet.automation.runner` e a chave `resources["divergencias"]` no
  snapshot, com as chaves `total`, `critica`, `atencao`, `aviso`, `alerta`,
  `parcial`, `motivo`. A Task 5 (dashboard) e a Task 4 (`/metrics`) leem esse
  formato.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/automation/test_runner.py` (o arquivo já importa
`run_collection`, `Settings`, `AuditEvent`, `DeviceSnapshot` e define `SAIDAS`,
`VaultFake` e `_dev_com_grupo`):

```python
def test_coleta_grava_resumo_das_divergencias(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6: o resumo do desejado × encontrado nasce na coleta, não na leitura."""
    dev = _dev_com_grupo(db_session, "r-resumo", "10.0.0.20")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = (
        db_session.query(DeviceSnapshot)
        .filter_by(device_id=dev.id)
        .order_by(DeviceSnapshot.id.desc())
        .first()
    )
    resumo = snap.resources["divergencias"]
    # Sem serviço cadastrado no SoT não há bloco desejado: as contagens ficam em
    # zero, e o que este teste prova é que a chave existe na coleta.
    assert resumo["total"] == 0
    assert (resumo["critica"], resumo["atencao"], resumo["aviso"], resumo["alerta"]) == (0, 0, 0, 0)
    assert isinstance(resumo["parcial"], bool)


def test_resumo_conta_severidades_e_marca_parcial(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gerenet.automation.reconcile import ReconcileItem, ReconcileResult

    dev = _dev_com_grupo(db_session, "r-resumo2", "10.0.0.21")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    def _resultado(session, device_id, *, snapshot_id=None):
        return ReconcileResult(
            device_id=device_id,
            snapshot_id=snapshot_id,
            aviso="Snapshot sem o recurso 'bgp_peers' — comparação parcial.",
            items=[
                ReconcileItem("subinterface.ausente", "critica", "GE0/0/1.10", "não listada", "recriar"),
                ReconcileItem("peer.orfao", "atencao", "100.64.0.2", "sem sessão", "conferir"),
                ReconcileItem("peer.para_baixo", "alerta", "2001:db8::2", "down", "conferir"),
            ],
        )

    monkeypatch.setattr("gerenet.automation.runner.reconciliar_device", _resultado)

    run_collection(dev.id, settings=settings, session_override=db_session)

    snap = (
        db_session.query(DeviceSnapshot)
        .filter_by(device_id=dev.id)
        .order_by(DeviceSnapshot.id.desc())
        .first()
    )
    resumo = snap.resources["divergencias"]
    assert resumo["total"] == 3
    assert (resumo["critica"], resumo["atencao"], resumo["aviso"], resumo["alerta"]) == (1, 1, 0, 1)
    assert resumo["parcial"] is True
    assert resumo["motivo"].startswith("Snapshot sem o recurso")


def test_falha_do_reconcile_nao_derruba_a_coleta(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coleta que trouxe dado do equipamento não vira `error` por cálculo derivado."""
    dev = _dev_com_grupo(db_session, "r-resumo3", "10.0.0.22")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    def _explode(*args, **kwargs):
        raise RuntimeError("render quebrou")

    monkeypatch.setattr("gerenet.automation.runner.reconciliar_device", _explode)

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = (
        db_session.query(DeviceSnapshot)
        .filter_by(device_id=dev.id)
        .order_by(DeviceSnapshot.id.desc())
        .first()
    )
    assert snap.status == "success"
    assert "divergencias" not in snap.resources
    evento = db_session.query(AuditEvent).filter_by(type="collect.reconcile_failed").one()
    assert evento.details["device_id"] == dev.id
    assert "render quebrou" in evento.details["error"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/automation/test_runner.py -q -k resumo`
Expected: FAIL — `KeyError: 'divergencias'` no primeiro, e no terceiro o evento
`collect.reconcile_failed` não existe.

- [ ] **Step 3: Implementar o resumo**

Em `src/gerenet/automation/runner.py`, acrescente o helper logo antes de
`run_collection`:

```python
def _resumo_divergencias(
    session: Session, device_id: int, snapshot_id: int, actor: str
) -> dict | None:
    """Contagem por severidade do desejado × encontrado, gravada na coleta (F6).

    Falha do reconcile NÃO derruba a coleta: o que veio do equipamento já está
    gravado e a divergência é derivada — marcar `job_runs` como `error` por causa
    dela seria mentira no histórico (§18). Devolve None quando não há resumo.
    """
    try:
        resultado = reconciliar_device(session, device_id, snapshot_id=snapshot_id)
    except Exception as exc:  # noqa: BLE001 — qualquer falha do cálculo é registrada e engolida
        session.add(
            models.AuditEvent(
                type="collect.reconcile_failed",
                actor=actor,
                details={"device_id": device_id, "snapshot_id": snapshot_id, "error": str(exc)},
            )
        )
        session.commit()
        return None
    resumo = {
        "total": len(resultado.items),
        "critica": 0,
        "atencao": 0,
        "aviso": 0,
        "alerta": 0,
        "parcial": resultado.aviso is not None,
        "motivo": resultado.aviso,
    }
    for item in resultado.items:
        resumo[item.severidade] = resumo.get(item.severidade, 0) + 1
    return resumo
```

E, em `run_collection`, entre o `sincronizar_mpls(session, snapshot)` e o
`return {"status": snapshot.status, ...}`:

```python
            # F6: resumo da divergência na própria coleta — dashboard e /metrics
            # leem daqui em vez de recalcular o desejado de todos (§20.1).
            resumo = _resumo_divergencias(session, dev.id, snapshot.id, actor)
            if resumo is not None:
                snapshot.resources = {**(snapshot.resources or {}), "divergencias": resumo}
                session.commit()
```

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/automation/test_runner.py -q`
Expected: PASS (todos os testes do arquivo, incluindo os 3 novos).

- [ ] **Step 5: Lint e commit**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

```bash
git add src/gerenet/automation/runner.py tests/automation/test_runner.py
git commit -m "feat(coleta): resumo da divergência gravado em cada coleta"
```

---

### Task 4: Endpoint Prometheus `/metrics`

**Files:**
- Create: `src/gerenet/api/metrics.py`
- Create: `tests/api/test_metrics.py`
- Modify: `src/gerenet/config.py` (setting `metrics_token`)
- Modify: `src/gerenet/api/main.py` (chamada antes do fallback da SPA)
- Modify: `pyproject.toml` + `uv.lock` (dependência `prometheus-client`)

**Interfaces:**
- Consumes: `resources["divergencias"]` (Task 3), `models.*`,
  `get_session()`, `Settings.redis_url`.
- Produces: `montar_metrics(app: FastAPI, settings: Settings) -> None` e
  `SEVERIDADES = ("critica", "atencao", "aviso", "alerta")` em
  `gerenet.api.metrics`; a rota `GET /metrics`; `Settings.metrics_token`.

- [ ] **Step 1: Instalar a dependência**

Run:
```bash
uv add "prometheus-client>=0.21"
```
Expected: `pyproject.toml` ganha `prometheus-client` em `dependencies` e o
`uv.lock` é atualizado. Confira com `grep -n prometheus pyproject.toml`.

- [ ] **Step 2: Escrever os testes que falham**

Crie `tests/api/test_metrics.py`:

```python
"""Contrato do /metrics (Fase 6, parte 1): as séries do §20.1 vêm do banco e do Redis."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device


def _cliente(**settings_kw) -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None, **settings_kw))
    return TestClient(create_app())


@pytest.fixture()
def ambiente(db_session: Session) -> models.Device:
    dev = create_device(
        db_session, DeviceCreate(name="r1", management_address="10.0.0.1"), actor="cli"
    )
    dev.comm_status = "ok"
    dev.consecutive_failures = 2
    db_session.add(
        models.DeviceSnapshot(
            device_id=dev.id,
            status="success",
            resources={
                "bgp_peers": [{"afi": "ipv4", "peer": "100.64.0.2", "estado": "Established"}],
                "divergencias": {
                    "total": 2, "critica": 1, "atencao": 1, "aviso": 0, "alerta": 0,
                    "parcial": False, "motivo": None,
                },
            },
            started_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    db_session.add(
        models.JobRun(
            device_id=dev.id, origin="cli", actor="cli", kind="collect", status="success",
            duration_ms=1500,
        )
    )
    dominio = models.MplsDomain(name="dom-metrics")
    db_session.add(dominio)
    db_session.flush()
    db_session.add_all([
        models.L2vcService(domain_id=dominio.id, vc_id=100, name="vc-metrics"),
        models.VsiService(domain_id=dominio.id, vsi_id=200, name="vsi-metrics", vrp_name="VSI-METRICS"),
        models.ChangeRequest(acao="provision", motivo="teste de métrica"),
    ])
    db_session.commit()
    return dev


def test_metrics_expoe_os_itens_do_20_1(ambiente: models.Device) -> None:
    resp = _cliente().get("/metrics")

    assert resp.status_code == 200
    corpo = resp.text
    assert 'gerenet_devices_comm_status{status="ok"} 1.0' in corpo
    assert 'gerenet_devices_active 1.0' in corpo
    assert 'gerenet_device_consecutive_failures{device="r1"} 2.0' in corpo
    assert 'gerenet_snapshot_age_seconds{device="r1"}' in corpo
    assert 'gerenet_divergencias{severidade="critica"} 1.0' in corpo
    assert 'gerenet_divergencias{severidade="atencao"} 1.0' in corpo
    assert "gerenet_devices_sem_resumo 0.0" in corpo
    assert 'gerenet_peers_bgp{estado="Established"} 1.0' in corpo
    assert 'gerenet_l2vc_oper_status{status="unknown"} 1.0' in corpo
    assert 'gerenet_vsi_oper_status{status="unknown"} 1.0' in corpo
    assert 'gerenet_change_requests{status="rascunho"} 1.0' in corpo
    assert 'gerenet_queue_jobs{queue="gerenet-collect"}' in corpo
    assert 'gerenet_queue_started{queue="gerenet-change"}' in corpo
    assert 'gerenet_job_runs{kind="collect",status="success",device="r1"} 1.0' in corpo
    assert 'gerenet_job_duration_seconds{kind="collect",quantil="0.5"} 1.5' in corpo


def test_metrics_conta_equipamento_sem_resumo(db_session: Session) -> None:
    dev = create_device(
        db_session, DeviceCreate(name="r2", management_address="10.0.0.2"), actor="cli"
    )
    db_session.add(
        models.DeviceSnapshot(device_id=dev.id, status="success", resources={})
    )
    db_session.commit()

    corpo = _cliente().get("/metrics").text

    assert "gerenet_devices_sem_resumo 1.0" in corpo


def test_metrics_exige_token_quando_configurado() -> None:
    cliente = _cliente(metrics_token="s3gr3do")

    assert cliente.get("/metrics").status_code == 401
    assert cliente.get("/metrics", headers={"Authorization": "Bearer errado"}).status_code == 401

    ok = cliente.get("/metrics", headers={"Authorization": "Bearer s3gr3do"})
    assert ok.status_code == 200
    assert "gerenet_" in ok.text


def test_metrics_nao_cai_no_fallback_da_spa(tmp_path: Path) -> None:
    """O catch-all da SPA responde qualquer GET: /metrics precisa vir antes dele."""
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>gerenet</html>", encoding="utf-8")

    resp = _cliente(static_dir=dist).get("/metrics")

    assert resp.status_code == 200
    assert "gerenet_" in resp.text
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_metrics.py -q`
Expected: FAIL — 404 no `/metrics` (e o import de `montar_metrics` ainda não existe).

- [ ] **Step 4: Adicionar o setting do token**

Em `src/gerenet/config.py`, depois de `collect_interval_minutes`:

```python
    # F6: token opcional do /metrics (Bearer). None = sem autenticação, como o
    # /healthz — o endpoint pertence à rede de gerência (§19).
    metrics_token: str | None = None
```

- [ ] **Step 5: Implementar o collector e a rota**

Crie `src/gerenet/api/metrics.py`:

```python
"""Endpoint Prometheus do gerenet (Fase 6, parte 1): os itens do §20.1.

Um Collector que lê o banco e o Redis a cada scrape — sem gauge mantido em
memória e sem processo de sincronização para morrer em silêncio. O registry é
por aplicação, e não o global do prometheus_client, porque a suíte chama
`create_app()` dezenas de vezes e o registro global duplicaria séries.

Sem `ProcessCollector`/`PlatformCollector`: o §20.1 não pede métrica de processo
e elas dependem de /proc, que não existe no macOS onde os testes rodam.
"""
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily
from redis import Redis
from rq import Queue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gerenet.config import Settings
from gerenet.db import get_session
from gerenet.domain import models
from gerenet.domain.models import COMM_STATUS

SEVERIDADES = ("critica", "atencao", "aviso", "alerta")
FILAS = ("gerenet-collect", "gerenet-change")
JANELA_DURACAO = 200  # jobs considerados no p50/p95 por tipo


def _ultimo_snapshot(session: Session, device_id: int) -> models.DeviceSnapshot | None:
    return session.scalars(
        select(models.DeviceSnapshot)
        .where(models.DeviceSnapshot.device_id == device_id)
        .order_by(models.DeviceSnapshot.id.desc())
        .limit(1)
    ).first()


def _por_status(session: Session, coluna) -> list[tuple[str, int]]:
    linhas = session.execute(select(coluna, func.count()).group_by(coluna)).all()
    return [(str(status), total) for status, total in linhas]


class ColetorGerenet:
    """Amostras do §20.1, calculadas no scrape."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def collect(self) -> Iterator[GaugeMetricFamily]:
        agora = datetime.now(UTC)
        amostras: list[GaugeMetricFamily] = []
        with get_session() as session:
            amostras.extend(self._devices(session, agora))
            amostras.extend(self._divergencias(session))
            amostras.extend(self._peers(session))
            amostras.extend(self._mpls(session))
            amostras.extend(self._mudancas(session))
            amostras.extend(self._jobs(session))
        amostras.extend(self._filas())
        yield from amostras

    def _devices(self, session: Session, agora: datetime) -> list[GaugeMetricFamily]:
        comm = GaugeMetricFamily(
            "gerenet_devices_comm_status",
            "Equipamentos por estado de comunicação (§20.1).",
            labels=["status"],
        )
        contagem = {status: 0 for status in COMM_STATUS}
        for status in session.scalars(select(models.Device.comm_status)):
            contagem[status] = contagem.get(status, 0) + 1
        for status, total in sorted(contagem.items()):
            comm.add_metric([status], total)

        ativos = GaugeMetricFamily("gerenet_devices_active", "Equipamentos com admin_status ligado.")
        ativos.add_metric(
            [],
            session.scalar(
                select(func.count()).select_from(models.Device).where(models.Device.admin_status.is_(True))
            )
            or 0,
        )

        idade = GaugeMetricFamily(
            "gerenet_snapshot_age_seconds",
            "Idade do snapshot mais recente, por equipamento (ausente = nunca coletado).",
            labels=["device"],
        )
        falhas = GaugeMetricFamily(
            "gerenet_device_consecutive_failures",
            "Falhas consecutivas de coleta, por equipamento.",
            labels=["device"],
        )
        for dev in session.scalars(select(models.Device).order_by(models.Device.name)):
            falhas.add_metric([dev.name], dev.consecutive_failures)
            snap = _ultimo_snapshot(session, dev.id)
            if snap is not None:
                idade.add_metric([dev.name], (agora - snap.started_at).total_seconds())
        return [comm, ativos, idade, falhas]

    def _divergencias(self, session: Session) -> list[GaugeMetricFamily]:
        divergencias = GaugeMetricFamily(
            "gerenet_divergencias",
            "Divergências da última coleta, por severidade (§10).",
            labels=["severidade"],
        )
        sem_resumo = GaugeMetricFamily(
            "gerenet_devices_sem_resumo",
            "Equipamentos com snapshot coletado antes do resumo de divergência existir.",
        )
        totais = {severidade: 0 for severidade in SEVERIDADES}
        contagem_sem = 0
        for dev in session.scalars(select(models.Device)):
            snap = _ultimo_snapshot(session, dev.id)
            if snap is None:
                continue
            resumo = (snap.resources or {}).get("divergencias")
            if not isinstance(resumo, dict):
                contagem_sem += 1
                continue
            for severidade in SEVERIDADES:
                totais[severidade] += int(resumo.get(severidade, 0) or 0)
        for severidade, total in sorted(totais.items()):
            divergencias.add_metric([severidade], total)
        sem_resumo.add_metric([], contagem_sem)
        return [divergencias, sem_resumo]

    def _peers(self, session: Session) -> list[GaugeMetricFamily]:
        peers = GaugeMetricFamily(
            "gerenet_peers_bgp",
            "Peers BGP do snapshot mais recente, por estado (§13.1).",
            labels=["estado"],
        )
        estados: dict[str, int] = {}
        for dev in session.scalars(select(models.Device)):
            snap = _ultimo_snapshot(session, dev.id)
            if snap is None:
                continue
            for linha in (snap.resources or {}).get("bgp_peers") or []:
                estado = str(linha.get("estado") or "desconhecido")
                estados[estado] = estados.get(estado, 0) + 1
        for estado, total in sorted(estados.items()):
            peers.add_metric([estado], total)
        return [peers]

    def _mpls(self, session: Session) -> list[GaugeMetricFamily]:
        l2vc = GaugeMetricFamily(
            "gerenet_l2vc_oper_status", "L2VCs por estado operacional (§9.2).", labels=["status"]
        )
        for status, total in _por_status(session, models.L2vcService.operational_status):
            l2vc.add_metric([status], total)
        vsi = GaugeMetricFamily(
            "gerenet_vsi_oper_status", "VSIs por estado operacional (§9.3).", labels=["status"]
        )
        for status, total in _por_status(session, models.VsiService.operational_status):
            vsi.add_metric([status], total)
        return [l2vc, vsi]

    def _mudancas(self, session: Session) -> list[GaugeMetricFamily]:
        mudancas = GaugeMetricFamily(
            "gerenet_change_requests", "Mudanças por status (§6.6).", labels=["status"]
        )
        for status, total in _por_status(session, models.ChangeRequest.status):
            mudancas.add_metric([status], total)
        return [mudancas]

    def _jobs(self, session: Session) -> list[GaugeMetricFamily]:
        runs = GaugeMetricFamily(
            "gerenet_job_runs",
            "Execuções acumuladas por tipo, status e equipamento (contagem do banco).",
            labels=["kind", "status", "device"],
        )
        linhas = session.execute(
            select(
                models.JobRun.kind,
                models.JobRun.status,
                func.coalesce(models.Device.name, "(sem equipamento)"),
                func.count(),
            )
            .join(models.Device, models.JobRun.device_id == models.Device.id, isouter=True)
            .group_by(models.JobRun.kind, models.JobRun.status, models.Device.name)
        ).all()
        for kind, status, device, total in linhas:
            runs.add_metric([kind, status, device], total)

        duracao = GaugeMetricFamily(
            "gerenet_job_duration_seconds",
            "p50 e p95 da duração por tipo de job (últimos 200 de cada tipo).",
            labels=["kind", "quantil"],
        )
        janela = (
            select(
                models.JobRun.kind.label("kind"),
                models.JobRun.duration_ms.label("duration_ms"),
                func.row_number()
                .over(partition_by=models.JobRun.kind, order_by=models.JobRun.id.desc())
                .label("rn"),
            )
            .subquery()
        )
        quantis = session.execute(
            select(
                janela.c.kind,
                func.percentile_cont(0.5).within_group(janela.c.duration_ms),
                func.percentile_cont(0.95).within_group(janela.c.duration_ms),
            )
            .where(janela.c.rn <= JANELA_DURACAO)
            .group_by(janela.c.kind)
        ).all()
        for kind, p50, p95 in quantis:
            duracao.add_metric([kind, "0.5"], float(p50) / 1000.0)
            duracao.add_metric([kind, "0.95"], float(p95) / 1000.0)
        return [runs, duracao]

    def _filas(self) -> list[GaugeMetricFamily]:
        jobs = GaugeMetricFamily("gerenet_queue_jobs", "Jobs aguardando na fila.", labels=["queue"])
        iniciados = GaugeMetricFamily(
            "gerenet_queue_started", "Jobs iniciados na fila.", labels=["queue"]
        )
        r = Redis.from_url(self._settings.redis_url)
        try:
            for nome in FILAS:
                fila = Queue(nome, connection=r)
                jobs.add_metric([nome], fila.count)
                iniciados.add_metric([nome], len(fila.started_job_registry.get_job_ids()))
        except Exception:  # noqa: BLE001 — Redis fora do ar não derruba o scrape inteiro
            pass
        finally:
            r.close()
        return [jobs, iniciados]


def montar_metrics(app: FastAPI, settings: Settings) -> None:
    """Registra GET /metrics (antes do fallback da SPA, que responde qualquer GET)."""
    registry = CollectorRegistry()
    registry.register(ColetorGerenet(settings))

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        token = settings.metrics_token
        if token and request.headers.get("Authorization") != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Token de métricas inválido.")
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
```

- [ ] **Step 6: Ligar a rota no app**

Em `src/gerenet/api/main.py`, acrescente o import junto dos outros de
`gerenet.api`:

```python
from gerenet.api.metrics import montar_metrics
```

E, dentro de `create_app()`, imediatamente antes do comentário do fallback da SPA:

```python
    montar_metrics(app, get_settings())
```

- [ ] **Step 7: Rodar os testes**

Run: `uv run pytest tests/api/test_metrics.py -q`
Expected: PASS (4 testes).

- [ ] **Step 8: Ver o endpoint de verdade**

Run:
```bash
uv run uvicorn gerenet.api.main:create_app --factory --port 8001 &
sleep 3
curl -s localhost:8001/metrics | grep -E "^gerenet_" | head -20
kill %1
```
Expected: linhas `gerenet_devices_comm_status{status=...}`, `gerenet_queue_jobs{...}`
e afins, com valores reais do banco dev (o processo usa o banco `gerenet`).

- [ ] **Step 9: Lint e commit**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

```bash
git add pyproject.toml uv.lock src/gerenet/config.py src/gerenet/api/metrics.py src/gerenet/api/main.py tests/api/test_metrics.py
git commit -m "feat(api): endpoint /metrics com os itens do §20.1"
```

---

### Task 5: Agregado de divergências no dashboard (API)

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (perto de `PerDeviceOut`, linha ~410)
- Modify: `src/gerenet/api/dashboard.py`
- Modify: `tests/api/test_dashboard_api.py`

**Interfaces:**
- Consumes: `resources["divergencias"]` (Task 3).
- Produces: `DivergenciasResumoOut` e `DivergenciasAggOut` em
  `gerenet.domain.schemas`; `PerDeviceOut.divergencias` (ou `null`);
  `DashboardOut.divergencias`. Campos do agregado: `total`, `critica`,
  `atencao`, `aviso`, `alerta`, `devices_com_critica`, `devices_sem_resumo`,
  `idade_max_seconds`. A Task 6 (web) consome exatamente esses nomes.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/api/test_dashboard_api.py`:

```python
def test_dashboard_agrega_divergencias_da_coleta(client: TestClient, db_session) -> None:
    env = _ambiente(db_session)
    com_resumo = create_device(
        db_session, DeviceCreate(name="dv1", management_address="10.0.0.11"), actor="cli"
    )
    sem_resumo = create_device(
        db_session, DeviceCreate(name="dv2", management_address="10.0.0.12"), actor="cli"
    )
    nao_coletado = create_device(
        db_session, DeviceCreate(name="dv3", management_address="10.0.0.13"), actor="cli"
    )
    started = datetime.now(UTC) - timedelta(minutes=30)
    db_session.add_all([
        models.DeviceSnapshot(
            device_id=com_resumo.id,
            status="success",
            resources={
                "divergencias": {
                    "total": 3, "critica": 1, "atencao": 2, "aviso": 0, "alerta": 0,
                    "parcial": False, "motivo": None,
                }
            },
            started_at=started,
        ),
        models.DeviceSnapshot(device_id=sem_resumo.id, status="success", resources={}),
    ])
    db_session.commit()
    assert nao_coletado.id  # sem snapshot: nem divergência, nem "sem resumo"

    dados = client.get("/api/v1/dashboard", headers=_auth()).json()

    assert dados["divergencias"] == {
        "total": 3,
        "critica": 1,
        "atencao": 2,
        "aviso": 0,
        "alerta": 0,
        "devices_com_critica": 1,
        "devices_sem_resumo": 1,
        "idade_max_seconds": pytest.approx(1800, abs=5),
    }
    por_nome = {p["name"]: p for p in dados["per_device"]}
    assert por_nome["dv1"]["divergencias"]["critica"] == 1
    assert por_nome["dv2"]["divergencias"] is None
    assert por_nome["dv3"]["divergencias"] is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_dashboard_api.py -q -k divergencias`
Expected: FAIL — `KeyError: 'divergencias'` na resposta.

- [ ] **Step 3: Adicionar os schemas**

Em `src/gerenet/domain/schemas.py`, antes de `PerDeviceOut`:

```python
class DivergenciasResumoOut(BaseModel):
    """Resumo do desejado × encontrado gravado pela coleta (F6)."""

    total: int
    critica: int
    atencao: int
    aviso: int
    alerta: int
    parcial: bool
    motivo: str | None = None


class DivergenciasAggOut(BaseModel):
    """Soma do resumo de todos os equipamentos + a contagem de quem não tem resumo."""

    total: int
    critica: int
    atencao: int
    aviso: int
    alerta: int
    devices_com_critica: int
    devices_sem_resumo: int
    idade_max_seconds: float | None
```

Em `PerDeviceOut`, depois de `active_job`:

```python
    divergencias: DivergenciasResumoOut | None = None
```

Em `DashboardOut`, depois de `per_device`:

```python
    divergencias: DivergenciasAggOut
```

- [ ] **Step 4: Calcular no dashboard**

Em `src/gerenet/api/dashboard.py`, ajuste os imports de schemas para incluir
`DivergenciasAggOut` e `DivergenciasResumoOut`.

No laço de `per_device`, o snapshot mais recente já está em mãos: guarde o
resumo lido dele.

```python
    per_device: list[PerDeviceOut] = []
    resumos: list[tuple[models.Device, models.DeviceSnapshot, DivergenciasResumoOut]] = []
    sem_resumo = 0
    for d in devices:
        # ... (código existente do snap/job/idade/per_device permanece)
        dado = (snap.resources or {}).get("divergencias") if snap is not None else None
        resumo = DivergenciasResumoOut(**dado) if isinstance(dado, dict) else None
        if snap is not None and resumo is None:
            sem_resumo += 1
        if snap is not None and resumo is not None:
            resumos.append((d, snap, resumo))
        per_device.append(
            PerDeviceOut(
                # ... (campos existentes)
                divergencias=resumo,
            )
        )
```

Monte o agregado logo antes do `return DashboardOut(...)`:

```python
    divergencias = DivergenciasAggOut(
        total=sum(r.total for _, _, r in resumos),
        critica=sum(r.critica for _, _, r in resumos),
        atencao=sum(r.atencao for _, _, r in resumos),
        aviso=sum(r.aviso for _, _, r in resumos),
        alerta=sum(r.alerta for _, _, r in resumos),
        devices_com_critica=sum(1 for _, _, r in resumos if r.critica > 0),
        devices_sem_resumo=sem_resumo,
        idade_max_seconds=(
            max((agora - snap.started_at).total_seconds() for _, snap, _ in resumos)
            if resumos
            else None
        ),
    )
```

E inclua `divergencias=divergencias` na construção de `DashboardOut`.

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/api/test_dashboard_api.py -q`
Expected: PASS (o teste novo e o `test_dashboard_agrega`, que não é afetado).

- [ ] **Step 6: Lint e commit**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

```bash
git add src/gerenet/domain/schemas.py src/gerenet/api/dashboard.py tests/api/test_dashboard_api.py
git commit -m "feat(dashboard): agregado de divergências por severidade"
```

---

### Task 6: Card de divergências no dashboard (web) e fumo e2e

**Files:**
- Modify: `web/src/api/types.ts` (perto de `PerDeviceOut`, linha ~209)
- Modify: `web/src/pages/Dashboard.tsx`
- Modify: `web/src/pages/Dashboard.test.tsx`
- Modify: `web/src/styles/global.css`
- Modify: `web/e2e/smoke.spec.ts`

**Interfaces:**
- Consumes: `GET /api/v1/dashboard` com `divergencias` (Task 5) e
  `per_device[].divergencias`; `SeverityBadge` (`web/src/components/SeverityBadge.tsx`);
  a rota `/reconcile?device_id=N` (já lida pela página de Reconciliação).
- Produces: card "Divergências da última coleta" na página do dashboard, com o
  bloco na faixa de saúde e a coluna na tabela por equipamento.

- [ ] **Step 1: Escrever os testes que falham**

Em `web/src/pages/Dashboard.test.tsx`, acrescente `divergencias` ao fixture
`DASH` (sem isso o componente quebra ao ler `data.divergencias`), com valores que
**não colidam** com as asserções existentes (o teste usa `getByText("2")` para as
mudanças pendentes e `getByText("25.0 h")` para a idade da coleta): use
`total: 1`, `critica: 1`, `atencao: 0`, `aviso: 0`, `alerta: 0` e
`idade_max_seconds: 3600` (renderiza "1.0 h").

```ts
const DASH = {
  // ... campos existentes
  divergencias: {
    total: 1,
    critica: 1,
    atencao: 0,
    aviso: 0,
    alerta: 0,
    devices_com_critica: 1,
    devices_sem_resumo: 1,
    idade_max_seconds: 3600,
  },
  per_device: [
    {
      // ... campos existentes do device
      divergencias: {
        total: 1,
        critica: 1,
        atencao: 0,
        aviso: 0,
        alerta: 0,
        parcial: false,
        motivo: null,
      },
    },
  ],
  // ... demais campos
};
```

E, no mesmo arquivo, um teste novo:

```tsx
  it("mostra o card de divergências com o link do equipamento crítico", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/v1/dashboard") {
          return new Response(JSON.stringify(DASH), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Divergências da última coleta" })).toBeTruthy();
    expect(screen.getByText(/1 equipamento\(s\) sem resumo/)).toBeTruthy();
    expect(screen.getByText(/resumo mais antigo há 1.0 h/)).toBeTruthy();
    const link = screen.getByRole("link", { name: "ne8000-01" });
    expect(link.getAttribute("href")).toBe("/reconcile?device_id=1");
  });
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd web && npm run test -- Dashboard`
Expected: FAIL — o heading do card não existe (e o primeiro teste quebra ao ler
`data.divergencias` antes da implementação).

- [ ] **Step 3: Tipar a resposta**

Em `web/src/api/types.ts`, antes de `PerDeviceOut`:

```ts
export interface DivergenciasResumoOut {
  total: number;
  critica: number;
  atencao: number;
  aviso: number;
  alerta: number;
  parcial: boolean;
  motivo: string | null;
}
export interface DivergenciasAggOut {
  total: number;
  critica: number;
  atencao: number;
  aviso: number;
  alerta: number;
  devices_com_critica: number;
  devices_sem_resumo: number;
  idade_max_seconds: number | null;
}
```

Em `PerDeviceOut`, depois de `active_job`:

```ts
  divergencias: DivergenciasResumoOut | null;
```

Em `DashboardOut`, depois de `per_device`:

```ts
  divergencias: DivergenciasAggOut;
```

- [ ] **Step 4: Implementar o card**

Em `web/src/pages/Dashboard.tsx`:

1. Imports novos:

```tsx
import { SeverityBadge } from "@/components/SeverityBadge";
import type { DivergenciasAggOut, PerDeviceOut } from "@/api/types";
```

2. Constantes e helper, junto de `formatarIdade`:

```tsx
const SEVERIDADES_DASH = ["critica", "atencao", "aviso", "alerta"] as const;

// "alerta" (anomalia de prefixos) compartilha o vermelho de "critica": é o
// mesmo critério do SeverityBadge, e o LED segue a faixa de saúde do topo.
function ledDivergencias(dv: DivergenciasAggOut): string {
  if (dv.critica + dv.alerta > 0) return "red";
  if (dv.atencao + dv.aviso > 0) return "amber";
  return "green";
}
```

3. Dentro de `Dashboard()`, depois de `idadeMax`:

```tsx
  const criticos = (data?.per_device ?? []).filter((d) => (d.divergencias?.critica ?? 0) > 0);
```

4. Um bloco novo na faixa de saúde, depois do bloco de "upstreams ativos":

```tsx
            <div className="metric">
              <span className={`led ${ledDivergencias(data.divergencias)}`} aria-hidden="true" />
              <span className="val">{data.divergencias.total}</span>
              <span className="label">divergências<br />na última coleta</span>
            </div>
```

5. O card, entre o parágrafo `.estados-equipamentos` e o `<h2>Equipamentos</h2>`:

```tsx
          <section className="divergencias" aria-label="Divergências da última coleta">
            <h2>Divergências da última coleta</h2>
            <p className="sub">
              Contagem do desejado × encontrado gravada em cada coleta; o detalhe fica na{" "}
              <Link to="/reconcile">Reconciliação</Link>.
              {data.divergencias.devices_sem_resumo > 0 &&
                ` ${data.divergencias.devices_sem_resumo} equipamento(s) sem resumo (coleta anterior a esta versão ou coleta sem snapshot).`}
            </p>
            <p className="severidades">
              {SEVERIDADES_DASH.map((s) => (
                <span key={s} className="severidade-contagem">
                  <SeverityBadge severidade={s} /> {data.divergencias[s]}
                </span>
              ))}
              {data.divergencias.idade_max_seconds != null && (
                <span className="sub">resumo mais antigo há {formatarIdade(data.divergencias.idade_max_seconds)}</span>
              )}
            </p>
            {criticos.length > 0 && (
              <p>
                Com divergência crítica:{" "}
                {criticos.map((d: PerDeviceOut) => (
                  <span key={d.device_id}>
                    <Link to={`/reconcile?device_id=${d.device_id}`}>{d.name}</Link>{" "}
                  </span>
                ))}
              </p>
            )}
          </section>
```

6. Uma coluna na tabela por equipamento, depois do `<th>Status</th>`:

```tsx
                  <th>Divergências</th>
```

com a célula correspondente, depois da célula de `StatusBadge`:

```tsx
                    <td>
                      {d.divergencias ? (
                        <Link to={`/reconcile?device_id=${d.device_id}`}>{d.divergencias.total}</Link>
                      ) : d.latest_snapshot ? (
                        "sem resumo"
                      ) : (
                        "—"
                      )}
                    </td>
```

- [ ] **Step 5: Estilo do card**

Em `web/src/styles/global.css`, ao lado das regras da faixa de saúde (perto de
`.estados-equipamentos`, linha ~226):

```css
.divergencias { margin: 0 0 1.2rem; }
.divergencias .sub { font-size: 0.85rem; color: var(--sub); }
.divergencias .severidades { display: flex; align-items: center; gap: 0.9rem; flex-wrap: wrap; margin: 0.4rem 0 0; }
.divergencias .severidade-contagem { display: inline-flex; align-items: center; gap: 0.35rem; }
```

- [ ] **Step 6: Rodar os testes web**

Run: `cd web && npm run test`
Expected: PASS (137 testes ou mais, 0 falhas). Se o primeiro teste falhar por
"found multiple elements", o valor novo do fixture colidiu com uma asserção
existente: troque o número do fixture (`total`/severidades) por um que não
apareça no corpo do teste.

- [ ] **Step 7: Build e lint**

Run: `cd web && npm run build && npm run lint`
Expected: build limpo (`tsc -b && vite build`) e lint sem avisos.

- [ ] **Step 8: Fumo e2e**

Pare o compose (a porta 8000 é do uvicorn do Playwright e o banco é o
`gerenet_e2e`, ver `web/e2e/README.md`):

Run: `docker compose stop api worker web`

Em `web/e2e/smoke.spec.ts`, no primeiro teste, depois de `await entrar(page);`:

```ts
  await expect(page.getByRole("heading", { name: "Divergências da última coleta" })).toBeVisible();
```

Run: `cd web && npm run test:e2e -- smoke.spec.ts`
Expected: PASS nos fumos do smoke (o card renderiza com o seed atual; sem
snapshot o card mostra zero e a nota de sem resumo, e o heading existe sempre).

- [ ] **Step 9: Commit**

```bash
git add web/src/api/types.ts web/src/pages/Dashboard.tsx web/src/pages/Dashboard.test.tsx web/src/styles/global.css web/e2e/smoke.spec.ts
git commit -m "feat(web): card de divergências na última coleta no dashboard"
```

---

### Task 7: Prometheus e Grafana no compose de dev

**Files:**
- Create: `docker/observability/prometheus.yml`
- Create: `docker/observability/grafana/provisioning/datasources/prometheus.yml`
- Create: `docker/observability/grafana/provisioning/dashboards/provider.yml`
- Create: `docker/observability/grafana/dashboards/gerenet.json`
- Modify: `compose.yaml` (serviços novos no fim, antes de `volumes:`)
- Modify: `README.md` (seção "Docker — dev completo (compose)")

**Interfaces:**
- Consumes: `GET /metrics` (Task 4), nos nomes de série definidos lá.
- Produces: serviços `prometheus` (9090) e `grafana` (3000) no compose, com o
  dashboard `gerenet` provisionado.

- [ ] **Step 1: Config do Prometheus**

Crie `docker/observability/prometheus.yml`:

```yaml
# Dev: raspa o /metrics da API do compose. Em produção, aponte o seu Prometheus
# para o /metrics da plataforma (rede de gerência, §19) — com
# GERENET_METRICS_TOKEN ligado, acrescente o bloco `authorization` no job.
global:
  scrape_interval: 30s
  scrape_timeout: 10s

scrape_configs:
  - job_name: gerenet
    metrics_path: /metrics
    static_configs:
      - targets: ["api:8000"]
```

- [ ] **Step 2: Provisionamento do Grafana**

Crie `docker/observability/grafana/provisioning/datasources/prometheus.yml`:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    uid: gerenet-prom
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

Crie `docker/observability/grafana/provisioning/dashboards/provider.yml`:

```yaml
apiVersion: 1

providers:
  - name: gerenet
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

- [ ] **Step 3: O dashboard**

Crie `docker/observability/grafana/dashboards/gerenet.json` com os painéis do
§20.1 (copie o JSON abaixo na íntegra; ele é a versão inicial, e quem opera
ajusta o que quiser no Grafana e exporta de volta):

```json
{
  "uid": "gerenet-operacao",
  "title": "gerenet — operação",
  "timezone": "browser",
  "schemaVersion": 39,
  "refresh": "1m",
  "editable": true,
  "time": { "from": "now-24h", "to": "now" },
  "panels": [
    {
      "id": 1,
      "type": "stat",
      "title": "Equipamentos por estado de comunicação",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 5, "w": 6, "x": 0, "y": 0 },
      "targets": [
        { "refId": "A", "expr": "gerenet_devices_comm_status", "legendFormat": "{{status}}" }
      ],
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] }
    },
    {
      "id": 2,
      "type": "stat",
      "title": "Coleta mais antiga",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 5, "w": 6, "x": 6, "y": 0 },
      "targets": [
        { "refId": "A", "expr": "max(gerenet_snapshot_age_seconds)", "legendFormat": "idade" }
      ],
      "fieldConfig": { "defaults": { "unit": "s" }, "overrides": [] }
    },
    {
      "id": 3,
      "type": "stat",
      "title": "Divergências por severidade",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 5, "w": 6, "x": 12, "y": 0 },
      "targets": [
        { "refId": "A", "expr": "gerenet_divergencias", "legendFormat": "{{severidade}}" }
      ],
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] }
    },
    {
      "id": 4,
      "type": "stat",
      "title": "Equipamentos sem resumo de divergência",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 5, "w": 6, "x": 18, "y": 0 },
      "targets": [
        { "refId": "A", "expr": "gerenet_devices_sem_resumo", "legendFormat": "sem resumo" }
      ],
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] }
    },
    {
      "id": 5,
      "type": "timeseries",
      "title": "Idade da coleta por equipamento",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 5 },
      "targets": [
        { "refId": "A", "expr": "gerenet_snapshot_age_seconds", "legendFormat": "{{device}}" }
      ],
      "fieldConfig": { "defaults": { "unit": "s" }, "overrides": [] }
    },
    {
      "id": 6,
      "type": "timeseries",
      "title": "Peers BGP por estado",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 5 },
      "targets": [
        { "refId": "A", "expr": "gerenet_peers_bgp", "legendFormat": "{{estado}}" }
      ],
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] }
    },
    {
      "id": 7,
      "type": "timeseries",
      "title": "Serviços MPLS por estado",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 8, "w": 8, "x": 0, "y": 13 },
      "targets": [
        { "refId": "A", "expr": "gerenet_l2vc_oper_status", "legendFormat": "l2vc {{status}}" },
        { "refId": "B", "expr": "gerenet_vsi_oper_status", "legendFormat": "vsi {{status}}" }
      ],
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] }
    },
    {
      "id": 8,
      "type": "timeseries",
      "title": "Mudanças por status",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 8, "w": 8, "x": 8, "y": 13 },
      "targets": [
        { "refId": "A", "expr": "gerenet_change_requests", "legendFormat": "{{status}}" }
      ],
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] }
    },
    {
      "id": 9,
      "type": "timeseries",
      "title": "Fila de jobs",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 8, "w": 8, "x": 16, "y": 13 },
      "targets": [
        { "refId": "A", "expr": "gerenet_queue_jobs", "legendFormat": "aguardando {{queue}}" },
        { "refId": "B", "expr": "gerenet_queue_started", "legendFormat": "iniciados {{queue}}" }
      ],
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] }
    },
    {
      "id": 10,
      "type": "timeseries",
      "title": "Duração da coleta (p50/p95)",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 21 },
      "targets": [
        {
          "refId": "A",
          "expr": "gerenet_job_duration_seconds",
          "legendFormat": "{{kind}} p{{quantil}}"
        }
      ],
      "fieldConfig": { "defaults": { "unit": "s" }, "overrides": [] }
    },
    {
      "id": 11,
      "type": "timeseries",
      "title": "Falhas consecutivas por equipamento",
      "datasource": { "type": "prometheus", "uid": "gerenet-prom" },
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 21 },
      "targets": [
        { "refId": "A", "expr": "gerenet_device_consecutive_failures", "legendFormat": "{{device}}" }
      ],
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] }
    }
  ]
}
```

- [ ] **Step 4: Serviços no compose**

Em `compose.yaml`, antes de `volumes:`:

```yaml
  # Observabilidade de dev (§20): raspa o /metrics da API e abre o dashboard
  # provisionado. Em produção, o Prometheus/Grafana são os de quem instala.
  prometheus:
    image: prom/prometheus:v2.55.1
    container_name: gerenet-prometheus
    volumes:
      - ./docker/observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports: ["9090:9090"]
    depends_on:
      - api

  grafana:
    image: grafana/grafana:11.3.0
    container_name: gerenet-grafana
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
      GF_AUTH_DISABLE_LOGIN_FORM: "true"
    volumes:
      - ./docker/observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./docker/observability/grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports: ["3000:3000"]
    depends_on:
      - prometheus
```

- [ ] **Step 5: Validar as configs sem subir a stack**

Run:
```bash
docker compose config -q
docker run --rm -v "$PWD/docker/observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro" prom/prometheus:v2.55.1 promtool check config /etc/prometheus/prometheus.yml
python -m json.tool docker/observability/grafana/dashboards/gerenet.json > /dev/null && echo "json ok"
```
Expected: `docker compose config -q` sem saída, `promtool` com
`SUCCESS: /etc/prometheus/prometheus.yml is valid prometheus config file` e
`json ok`. Nada disso toca os containers que já estão no ar.

- [ ] **Step 6: Conferir a coleta de ponta a ponta (manual, no fim da frente)**

Com a stack de dev de pé (`docker compose up -d --build`), abra
`http://localhost:3000` e confira no dashboard `gerenet — operação` que os
painéis têm série (o alvo deve aparecer UP em `http://localhost:9090/targets`).
Esta é a conferência registrada no runbook da Task 8.

- [ ] **Step 7: README**

Na seção "Docker — dev completo (compose)" do `README.md`, depois da lista de
comandos (`docker compose exec api …`), acrescente:

```markdown
Observabilidade de dev: `docker compose up -d prometheus grafana` sobe o
Prometheus (http://localhost:9090) e o Grafana (http://localhost:3000, acesso
anônimo como viewer) com o dashboard `gerenet — operação` provisionado, raspando
`api:8000/metrics` a cada 30 s. A plataforma expõe os itens do §20.1 no
`/metrics`; com `GERENET_METRICS_TOKEN` preenchido, o endpoint pede
`Authorization: Bearer <token>` e o job do Prometheus precisa do mesmo valor.
```

- [ ] **Step 8: Commit**

```bash
git add compose.yaml README.md docker/observability
git commit -m "feat(compose): prometheus e grafana de dev com o dashboard do §20.1"
```

---

### Task 8: Documentação e registro

**Files:**
- Modify: `docs/wiki/equipamentos.md` (seção nova depois de "## Jobs: a fila de coleta")
- Modify: `docs/wiki/operacao.md` (seções "## O que a reconciliação mostra" e "## Jobs de coleta e erros comuns")
- Create: `docs/runbook-observabilidade.md`
- Modify: `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md` (§25 e §22)
- Modify: `CLAUDE.md` (lista de "Estado do repositório")

**Interfaces:**
- Consumes: tudo das Tasks 1 a 7 (nomes de env, eventos de auditoria, séries).
- Produces: documentação de operação e o registro das decisões da frente.

- [ ] **Step 1: Wiki — coleta periódica**

Em `docs/wiki/equipamentos.md`, depois de "## Jobs: a fila de coleta":

```markdown
## Coleta periódica

Com `GERENET_COLLECT_INTERVAL_MINUTES` maior que zero, o worker arma uma
varredura que enfileira a coleta dos equipamentos **ativos e com grupo de
credencial** no intervalo configurado (default 0, desligado). Mudar o valor pede
restart do worker: o arm acontece na subida, e a varredura se reagenda ao fim de
cada execução.

- Quem foi coletado dentro do intervalo é pulado, então coletar à mão minutos
  antes da varredura adia aquele equipamento para a próxima (o intervalo entre
  coletas de um equipamento pode chegar a 2× o configurado).
- Cada varredura deixa um evento `collect.sweep` na auditoria, com quantos
  equipamentos foram enfileirados, quantos foram pulados por idade e o motivo de
  cada recusa (coleta em andamento ou já pendente).
- A coleta agendada aparece nos jobs com `origin = scheduler`, o que a distingue
  da coleta manual.
```

- [ ] **Step 2: Wiki — resumo da divergência**

Em `docs/wiki/operacao.md`, no fim de "## O que a reconciliação mostra":

```markdown
### Divergências da última coleta

Cada coleta grava, no próprio snapshot, a contagem do desejado × encontrado por
severidade (`resources["divergencias"]`). O **card do dashboard** mostra essa
contagem sem recalcular nada, e o detalhe item a item continua nesta página, sob
demanda.

Equipamento coletado antes desta versão não tem o resumo, e o card diz quantos
são: *sem resumo* é diferente de *sem divergência*, e o painel não soma zero
onde ninguém olhou. Quando a comparação é parcial (faltou um recurso no
snapshot), o resumo marca `parcial` e guarda o motivo.
```

No fim de "## Jobs de coleta e erros comuns":

```markdown
Falha ao calcular a divergência **não** derruba a coleta: o snapshot fica sem o
resumo e a auditoria registra `collect.reconcile_failed` com o erro. Se o card
mostrar equipamentos sem resumo, confira esse evento antes de suspeitar da
coleta.
```

- [ ] **Step 3: Runbook de observabilidade**

Crie `docs/runbook-observabilidade.md`:

```markdown
# Runbook — observabilidade (métricas e Grafana)

Vale para a Fase 6, parte 1: coleta periódica, resumo de divergência na coleta e
o endpoint Prometheus.

## O que a plataforma expõe

`GET /metrics`, no mesmo processo da API, com os itens do §20.1: equipamentos por
estado de comunicação, idade do snapshot e falhas consecutivas por equipamento,
divergências por severidade, peers BGP por estado, L2VC e VSI por estado,
mudanças por status, fila de jobs e duração de tarefa (p50/p95).

O endpoint pertence à **rede de gerência** (§19): não tem autenticação de sessão,
como o `/healthz`. Com `GERENET_METRICS_TOKEN` preenchido, ele exige
`Authorization: Bearer <token>` — e o scrape precisa mandar o mesmo valor.

O worker **não** expõe `/metrics`: cada job roda num processo filho (`os.fork`) e
métricas em memória morreriam com ele. As métricas de job vêm do `job_runs`, que
é durável.

## Dev: Prometheus e Grafana do compose

```bash
docker compose up -d prometheus grafana
```

- Prometheus em http://localhost:9090 (`/targets` mostra o alvo `gerenet`);
- Grafana em http://localhost:3000, acesso anônimo como viewer, com o dashboard
  `gerenet — operação` já provisionado (arquivos em `docker/observability/`).

Sem dado nos painéis: confira primeiro `/targets` (alvo UP) e depois
`curl -s localhost:8000/metrics | head`. Com o token ligado, o job do
`prometheus.yml` precisa do bloco `authorization`.

## Produção

Aponte o Prometheus de casa para o `/metrics` da plataforma, pela rede de
gerência. Os dois arquivos que importam são os do repo (`prometheus.yml` e o JSON
do dashboard), e o resto é ajuste local. Se a API estiver atrás de proxy, o
`/metrics` precisa ser roteado como o resto.

## Coleta periódica

`GERENET_COLLECT_INTERVAL_MINUTES` (0 = desligado) liga a varredura; o worker
arma na subida, então mudar o valor pede restart do worker. Os números de cada
varredura estão no evento `collect.sweep` da auditoria. A wiki de equipamentos
tem as regras (idade, 2×, recusas).
```

- [ ] **Step 4: Registrar a emenda na spec**

Em `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md`, no §25, depois do item 18:

```markdown
Complementos registrados em 2026-09-14 (Fase 6, parte 1):

19. **`/metrics` só na API (emenda ao item 15)**: o item 15 prometia o endpoint
    Prometheus "na API e no worker". O RQ executa cada job num processo filho
    (`os.fork`), então contador em memória criado dentro do job morre com o
    filho; sustentar métricas no worker exigiria o modo multiprocesso do
    `prometheus_client` (diretório compartilhado, semântica de gauge própria).
    As métricas de tarefa saem do `job_runs`, que é durável e sobrevive a restart
    do worker. O modo multiprocesso fica registrado como caminho para métricas de
    processo, quando houver razão.
20. **Coleta periódica e resumo da divergência**: o agendamento mora no próprio
    worker (`with_scheduler` do RQ), com arm na subida e rearm ao fim de cada
    varredura, e o intervalo é global
    (`GERENET_COLLECT_INTERVAL_MINUTES`, 0 = desligado). Cada coleta grava o
    resumo do desejado × encontrado por severidade em `snapshot.resources`;
    falha do reconcile não derruba a coleta (evento `collect.reconcile_failed`).
```

No §22, na Fase 6, acrescente ao fim do bloco (como nota, sem renumerar os
itens):

```markdown
Entregue em 2026-09-14 (parte 1): reconciliação agendada (coleta periódica com
resumo de divergência em cada coleta) e Grafana (dashboard do §20.1 sobre o
`/metrics`). Seguem pendentes: notificações, API de ativação para sistemas
externos, relatórios operacionais, Zabbix e NetBox.
```

- [ ] **Step 5: Estado do repositório no CLAUDE.md**

Em `CLAUDE.md`, ao fim da lista "Estado do repositório", acrescente um bullet:

```markdown
- Fase 6, parte 1 (automação contínua, 2026-09-14): **coleta periódica** —
  `GERENET_COLLECT_INTERVAL_MINUTES` (0 = desligado) liga a varredura no worker
  (`with_scheduler=True`, arm na subida e rearm ao fim de cada execução), que
  enfileira os equipamentos ativos com credencial reusando `enqueue_collect`
  (lock/dedupe/recusas valem como na coleta manual), pula quem foi coletado
  dentro do intervalo (pior caso ~2×) e audita `collect.sweep` com os números;
  mudar o intervalo pede restart do worker. Cada coleta passou a gravar
  `resources["divergencias"]` (contagem por severidade + `parcial`/`motivo`) e
  falha do reconcile **não** derruba a coleta (`collect.reconcile_failed`).
  **`/metrics`** na API (`gerenet.api.metrics`, `CollectorRegistry` por app,
  sem auth como o `/healthz`, token opcional `GERENET_METRICS_TOKEN`), com os
  nove itens do §20.1 derivados do banco/Redis (jobs por tipo/status/equipamento
  e p50/p95 de duração em SQL) — o worker **não** expõe endpoint (fork por job;
  emenda registrada ao §25.15); **Prometheus e Grafana** no compose de dev
  (`docker/observability/`, dashboard `gerenet — operação`) e card de
  divergências no dashboard (lê o resumo, linka `/reconcile?device_id=N`).
  Dependência nova: `prometheus-client`. Runbook em
  `docs/runbook-observabilidade.md`.
```

- [ ] **Step 6: Rodar a suíte completa**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: PASS em tudo, sem regressão (a base era 865; a frente soma os testes de
sweep, runner, métricas e dashboard).

Run: `cd web && npm run build && npm run test && npm run lint`
Expected: PASS.

Verificação final antes de dizer que acabou (evidência antes da afirmação,
`superpowers:verification-before-completion`).

- [ ] **Step 7: Commit**

```bash
git add docs/wiki/equipamentos.md docs/wiki/operacao.md docs/runbook-observabilidade.md ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md CLAUDE.md
git commit -m "docs(fase6): wiki, runbook de observabilidade e registro das decisões"
```

---

## Self-Review

**Cobertura do spec:** as oito decisões da seção 10 do design têm task — (1)
agendamento no worker → Tasks 1 e 2; (2) intervalo global → Task 1; (3) resumo no
snapshot → Task 3; (4) falha do reconcile não derruba → Task 3; (5) `/metrics` só
na API com emenda → Tasks 4 e 8; (6) sem auth por padrão com token opcional →
Task 4; (7) registry por aplicação → Task 4; (8) notificações fora → fora por
escopo. As seções 3 a 9 do design mapeiam em Tasks 1 a 8, e a tabela de séries do
§5 tem um teste por família na Task 4.

**Ordem e dependências:** Tasks 1 e 2 são sequenciais (a 2 usa a varredura da 1);
a 3 é independente das duas e pode rodar em paralelo se houver dois executores; a
4 e a 5 dependem da 3 (leem o resumo); a 6 depende da 5; a 7 depende da 4; a 8
fecha.

**Consistência de nomes:** `varredura_coletas`, `armar_varredura`, `SWEEP_LOCK`,
`SWEEP_JOB_TIMEOUT`, `liberta_lock`, `_resumo_divergencias` (privado, usado só
dentro do runner), `montar_metrics`, `SEVERIDADES`, `ColetorGerenet`,
`DivergenciasResumoOut`, `DivergenciasAggOut`, `ledDivergencias`,
`SEVERIDADES_DASH` aparecem com o mesmo nome onde são consumidos. As chaves do
resumo (`total`, `critica`, `atencao`, `aviso`, `alerta`, `parcial`, `motivo`)
são as mesmas na Task 3, na Task 4, na Task 5 e nos fixtures da Task 6.

**Riscos de colisão já mapeados:** os valores do fixture web (Task 6, Step 1)
foram escolhidos para não colidir com `getByText("2")` nem com `getByText("25.0 h")`
do teste existente; o `queue_started` da API pode variar se o worker do compose
estiver rodando, por isso o teste de métricas só afirma a presença da série, e
não o valor.
