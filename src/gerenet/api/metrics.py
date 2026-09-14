"""Endpoint Prometheus do gerenet (Fase 6, parte 1): os itens do §20.1.

Um Collector que lê o banco e o Redis a cada scrape — sem gauge mantido em
memória e sem processo de sincronização para morrer em silêncio. O registry é
por aplicação, e não o global do prometheus_client, porque a suíte chama
`create_app()` dezenas de vezes e o registro global duplicaria séries.

Sem `ProcessCollector`/`PlatformCollector`: o §20.1 não pede métrica de processo
e elas dependem de /proc, que não existe no macOS onde os testes rodam.
"""
import logging
import secrets
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

logger = logging.getLogger(__name__)

SEVERIDADES = ("critica", "atencao", "aviso", "alerta")
FILAS = ("gerenet-collect", "gerenet-change")
JANELA_DURACAO = 200  # jobs considerados no p50/p95 por tipo


def _ultimos_snapshots(session: Session) -> dict[int, models.DeviceSnapshot]:
    """Snapshot mais recente de cada equipamento, em uma consulta (max(id))."""
    ultimos = (
        select(
            models.DeviceSnapshot.device_id,
            func.max(models.DeviceSnapshot.id).label("snapshot_id"),
        )
        .group_by(models.DeviceSnapshot.device_id)
        .subquery()
    )
    snapshots = session.scalars(
        select(models.DeviceSnapshot).join(
            ultimos, models.DeviceSnapshot.id == ultimos.c.snapshot_id
        )
    )
    return {snap.device_id: snap for snap in snapshots}


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
            # Duas consultas fixas (equipamentos e o último snapshot de cada um), o
            # resto em agregações: o custo do scrape não cresce com o parque.
            devices = list(session.scalars(select(models.Device).order_by(models.Device.name)))
            por_device = _ultimos_snapshots(session)
            amostras.extend(self._devices(devices, por_device, agora))
            amostras.extend(self._divergencias(devices, por_device))
            amostras.extend(self._peers(devices, por_device))
            amostras.extend(self._mpls(session))
            amostras.extend(self._mudancas(session))
            amostras.extend(self._jobs(session))
        amostras.extend(self._filas())
        yield from amostras

    def _devices(
        self,
        devices: list[models.Device],
        por_device: dict[int, models.DeviceSnapshot],
        agora: datetime,
    ) -> list[GaugeMetricFamily]:
        comm = GaugeMetricFamily(
            "gerenet_devices_comm_status",
            "Equipamentos por estado de comunicação (§20.1).",
            labels=["status"],
        )
        contagem = {status: 0 for status in COMM_STATUS}
        for dev in devices:
            contagem[dev.comm_status] = contagem.get(dev.comm_status, 0) + 1
        for status, total in sorted(contagem.items()):
            comm.add_metric([status], total)

        ativos = GaugeMetricFamily("gerenet_devices_active", "Equipamentos com admin_status ligado.")
        ativos.add_metric([], sum(1 for dev in devices if dev.admin_status))

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
        for dev in devices:
            falhas.add_metric([dev.name], dev.consecutive_failures)
            snap = por_device.get(dev.id)
            if snap is not None:
                idade.add_metric([dev.name], (agora - snap.started_at).total_seconds())
        return [comm, ativos, idade, falhas]

    def _divergencias(
        self, devices: list[models.Device], por_device: dict[int, models.DeviceSnapshot]
    ) -> list[GaugeMetricFamily]:
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
        for dev in devices:
            snap = por_device.get(dev.id)
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

    def _peers(
        self, devices: list[models.Device], por_device: dict[int, models.DeviceSnapshot]
    ) -> list[GaugeMetricFamily]:
        peers = GaugeMetricFamily(
            "gerenet_peers_bgp",
            "Peers BGP do snapshot mais recente, por estado (§13.1).",
            labels=["estado"],
        )
        estados: dict[str, int] = {}
        for dev in devices:
            snap = por_device.get(dev.id)
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
            # duration_ms = 0 é linha sem medição (queued/running e o erro gravado no
            # caminho de falha do runner): como duração, puxaria o quantil para baixo.
            .where(janela.c.rn <= JANELA_DURACAO, janela.c.duration_ms > 0)
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
        except Exception as exc:  # noqa: BLE001 — Redis fora do ar não derruba o scrape inteiro
            # Só o tipo: a mensagem do redis-py pode carregar a URL (com senha).
            logger.warning("metrics.filas_indisponiveis: %s", type(exc).__name__)
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
        if token:
            # Em bytes: compare_digest com str levanta TypeError em caractere
            # não-ASCII, e o header do cliente viraria 500 em vez de 401.
            apresentado = (request.headers.get("Authorization") or "").encode()
            if not secrets.compare_digest(apresentado, f"Bearer {token}".encode()):
                raise HTTPException(status_code=401, detail="Token de métricas inválido.")
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
