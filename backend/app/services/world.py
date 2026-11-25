"""세계관 인물·장소 등록. 이름 중복은 같은 kind 안에서 공백·대소문자를 무시하고 거른다."""
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.models.world import WorldEntity
from app.repositories import world as world_repo
from app.schemas.world import (
    WorldEntityCreate,
    WorldEntityListResponse,
    WorldEntityResponse,
    WorldEntityUpdate,
)
from app.services.transactions import commit, rollback


def normalize_name(name: str) -> str:
    """이름 비교용. 앞뒤 공백을 빼고 대소문자를 구분하지 않는다.

    저장 값에는 쓰지 않는다. 요소 매칭도 이 함수로 같은 이름을 찾는다.
    """
    return name.strip().casefold()


def _response(entity: WorldEntity) -> WorldEntityResponse:
    return WorldEntityResponse(
        id=entity.id,
        kind=entity.kind,
        name=entity.name,
        age_range=entity.age_range,
        hair=entity.hair,
        outfit=entity.outfit,
        features=entity.features,
        created_at=entity.created_at,
    )


def _duplicate(
    db: Session, kind: str, name: str, *, exclude_id: int | None = None
) -> WorldEntity | None:
    key = normalize_name(name)
    for entity in world_repo.list_entities(db, kind):
        if entity.id != exclude_id and normalize_name(entity.name) == key:
            return entity
    return None


_DUPLICATE_MESSAGE = {
    "person": "같은 이름의 인물이 이미 있습니다.",
    "place": "같은 이름의 장소가 이미 있습니다.",
}


def _reject_duplicate(existing: WorldEntity) -> None:
    raise ValidationFailed(
        _DUPLICATE_MESSAGE.get(existing.kind, "같은 이름이 이미 있습니다."),
        {"field": "name", "reason": "duplicate", "existing_id": existing.id},
    )


def list_entities(db: Session, kind: str | None = None) -> WorldEntityListResponse:
    """kind가 없으면 전체. 순서는 만든 순서(id)다. kind는 person, place, None만 넘긴다."""
    rows = world_repo.list_entities(db, kind)
    return WorldEntityListResponse(entities=[_response(row) for row in rows])


def create_entity(db: Session, body: WorldEntityCreate) -> WorldEntityResponse:
    existing = _duplicate(db, body.kind, body.name)
    if existing is not None:
        _reject_duplicate(existing)
    try:
        entity = world_repo.create_entity(
            db,
            name=body.name,
            kind=body.kind,
            hair=body.hair,
            outfit=body.outfit,
            age_range=body.age_range,
            features=body.features,
        )
        commit(db)
    except Exception:
        rollback(db)
        raise
    return _response(entity)


def get_entity(db: Session, entity_id: int) -> WorldEntityResponse:
    entity = world_repo.get_entity(db, entity_id)
    if entity is None:
        raise NotFound("세계관 항목을 찾을 수 없습니다.", {"entity_id": entity_id})
    return _response(entity)


def update_entity(db: Session, entity_id: int, body: WorldEntityUpdate) -> WorldEntityResponse:
    """보낸 칸만 저장한다. 이름이나 kind가 다른 항목과 겹치면 아무것도 바꾸지 않는다."""
    current = world_repo.get_entity(db, entity_id)
    if current is None:
        raise NotFound("세계관 항목을 찾을 수 없습니다.", {"entity_id": entity_id})
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields or "kind" in fields:
        existing = _duplicate(
            db,
            fields.get("kind", current.kind),
            fields.get("name", current.name),
            exclude_id=current.id,
        )
        if existing is not None:
            _reject_duplicate(existing)
    try:
        updated = world_repo.update_entity(db, entity_id, **fields)
        if updated is None:
            raise NotFound("세계관 항목을 찾을 수 없습니다.", {"entity_id": entity_id})
        commit(db)
    except Exception:
        rollback(db)
        raise
    return _response(updated)
