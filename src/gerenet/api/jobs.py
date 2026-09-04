from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from gerenet.api.deps import SessionDep, require_actor
from gerenet.domain import models
from gerenet.domain.schemas import JobRunOut

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"], dependencies=[Depends(require_actor)])


@router.get("", response_model=list[JobRunOut])
def listar(
    session: SessionDep,
    device_id: int | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list:
    stmt = select(models.JobRun).order_by(models.JobRun.id.desc()).limit(limit).offset(offset)
    if device_id is not None:
        stmt = stmt.where(models.JobRun.device_id == device_id)
    if status is not None:
        stmt = stmt.where(models.JobRun.status == status)
    if kind is not None:
        stmt = stmt.where(models.JobRun.kind == kind)
    return list(session.scalars(stmt))


@router.get("/{job_id}", response_model=JobRunOut)
def detalhar(job_id: int, session: SessionDep) -> object:
    job = session.get(models.JobRun, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    return job
