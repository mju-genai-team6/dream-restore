"""세계관 인물·장소 등록 (S4 선택)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import error_responses
from app.schemas.world import (
    WorldEntityCreate,
    WorldEntityListQuery,
    WorldEntityListResponse,
    WorldEntityResponse,
    WorldEntityUpdate,
)
from app.services import world as world_service

router = APIRouter(prefix="/world", tags=["world"])


def _kind_filter(
    kind: Annotated[str | None, Query(description="person 또는 place. 없으면 전체")] = None,
) -> str | None:
    try:
        return WorldEntityListQuery.model_validate({"kind": kind}).kind
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


@router.get(
    "/entities",
    response_model=WorldEntityListResponse,
    summary="세계관 인물·장소 목록 (만든 순서)",
    responses=error_responses(400),
)
def list_entities(
    db: Annotated[Session, Depends(get_db)],
    kind: Annotated[str | None, Depends(_kind_filter)] = None,
) -> WorldEntityListResponse:
    return world_service.list_entities(db, kind)


@router.post(
    "/entities",
    response_model=WorldEntityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="세계관 인물·장소 등록",
    responses=error_responses(400),
)
def create_entity(
    body: WorldEntityCreate, db: Annotated[Session, Depends(get_db)]
) -> WorldEntityResponse:
    return world_service.create_entity(db, body)


@router.get(
    "/entities/{entity_id}",
    response_model=WorldEntityResponse,
    summary="세계관 인물·장소 조회",
    responses=error_responses(404),
)
def get_entity(entity_id: int, db: Annotated[Session, Depends(get_db)]) -> WorldEntityResponse:
    return world_service.get_entity(db, entity_id)


@router.patch(
    "/entities/{entity_id}",
    response_model=WorldEntityResponse,
    summary="세계관 인물·장소 수정 (보낸 항목만)",
    responses=error_responses(400, 404),
)
def update_entity(
    entity_id: int,
    body: WorldEntityUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> WorldEntityResponse:
    return world_service.update_entity(db, entity_id, body)
