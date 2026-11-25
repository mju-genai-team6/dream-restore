"""세계관 인물·장소 등록. 이름 중복은 같은 kind 안에서 공백·대소문자를 무시하고 거른다."""
import logging

from sqlalchemy.orm import Session

from app.core.enums import ElementType
from app.core.errors import NotFound, ValidationFailed
from app.models.world import WorldEntity
from app.repositories import extractions as extraction_repo
from app.repositories import world as world_repo
from app.schemas.world import (
    WorldEntityCreate,
    WorldEntityListResponse,
    WorldEntityResponse,
    WorldEntityUpdate,
)
from app.services.transactions import commit, rollback

logger = logging.getLogger(__name__)

_LINKABLE = frozenset({ElementType.PERSON.value, ElementType.PLACE.value})


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


def link_dream_elements_to_world(db: Session, dream_id: int) -> int:
    """최신 추출의 미연결 person·place 요소를 같은 kind·같은 이름의 세계관 항목에 붙인다.

    요소의 name만 비교한다. name_en은 쓰지 않는다. commit하지 않는다.
    한 요소가 실패하거나 목록을 읽지 못해도 예외를 밖으로 던지지 않는다.
    """
    try:
        return _link_unlinked_elements(db, dream_id)
    except Exception as exc:  # noqa: BLE001 - 연결 실패가 장면 작업을 멈추면 안 된다
        logger.warning("꿈 %s 요소를 세계관에 연결하지 못했습니다: %s", dream_id, exc)
        return 0


def _link_unlinked_elements(db: Session, dream_id: int) -> int:
    elements = [
        element
        for element in extraction_repo.list_elements(db, dream_id)
        if element.type in _LINKABLE and element.entity_id is None
    ]
    kinds = {element.type for element in elements}
    ids_by_kind = {kind: _entity_ids_by_name(db, kind) for kind in kinds}
    linked = 0
    for element in elements:
        try:
            key = normalize_name(element.name)
            entity_id = ids_by_kind.get(element.type, {}).get(key)
            if entity_id is None:
                continue
            extraction_repo.link_element_entity(db, element.id, entity_id)
        except Exception as exc:  # noqa: BLE001 - 이 요소만 건너뛰고 장면 저장은 계속한다
            logger.warning(
                "꿈 %s 요소 %s를 세계관에 연결하지 않습니다: %s",
                dream_id,
                element.id,
                exc,
            )
            continue
        linked += 1
    logger.info("꿈 %s 세계관 연결 %s건", dream_id, linked)
    return linked


def _entity_ids_by_name(db: Session, kind: str) -> dict[str, int]:
    """kind 안에서 비교용 이름 → id. 같은 이름이면 id가 작은 항목을 쓴다."""
    found: dict[str, int] = {}
    for entity in world_repo.list_entities(db, kind):
        found.setdefault(normalize_name(entity.name), entity.id)
    return found
