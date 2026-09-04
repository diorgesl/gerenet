"""Catálogo de communities (§25.6) — read-only no ciclo B (spec §8)."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import CommunityOut
from gerenet.domain.services import communities as svc

router = APIRouter(
    prefix="/api/v1/communities", tags=["communities"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[CommunityOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_communities(session, include_disabled=include_disabled)
