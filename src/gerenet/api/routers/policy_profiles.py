from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import PolicyProfileOut
from gerenet.domain.services import policy_profiles as svc
from gerenet.domain.services.errors import ValidationError

router = APIRouter(
    prefix="/api/v1/policy-profiles",
    tags=["policy-profiles"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[PolicyProfileOut])
def listar(
    session: SessionDep, direction: str | None = None, include_disabled: bool = False
) -> list:
    """Catálogo de produtos de roteamento — somente leitura (§6.5/§25.5)."""
    try:
        return svc.list_policy_profiles(
            session, direction=direction, include_disabled=include_disabled
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
