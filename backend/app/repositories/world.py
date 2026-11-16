"""(선택, S4) 세계관 인물·장소 (world_entities)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorldEntity

_EDITABLE = ("name", "kind", "hair", "outfit", "age_range", "features")


def create_entity(
    db: Session,
    *,
    name: str,
    kind: str,
    hair: str | None = None,
    outfit: str | None = None,
    age_range: str | None = None,
    features: str | None = None,
) -> WorldEntity:
    """kind: person, place."""
    entity = WorldEntity(name=name, kind=kind, hair=hair, outfit=outfit, age_range=age_range, features=features)
    db.add(entity)
    db.flush()
    db.refresh(entity)
    return entity


def get_entity(db: Session, entity_id: int) -> WorldEntity | None:
    return db.get(WorldEntity, entity_id)


def list_entities(db: Session, kind: str | None = None) -> list[WorldEntity]:
    query = select(WorldEntity).order_by(WorldEntity.id)
    if kind is not None:
        query = query.where(WorldEntity.kind == kind)
    return list(db.scalars(query))


def update_entity(db: Session, entity_id: int, **fields) -> WorldEntity | None:
    """넘긴 항목만 바꾼다 (name, kind, hair, outfit, age_range, features). 없으면 None."""
    unknown = set(fields) - set(_EDITABLE)
    if unknown:
        raise TypeError(f"바꿀 수 없는 항목: {sorted(unknown)}")
    entity = db.get(WorldEntity, entity_id)
    if entity is None:
        return None
    for key, value in fields.items():
        setattr(entity, key, value)
    db.flush()
    return entity
