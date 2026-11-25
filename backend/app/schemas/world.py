"""세계관 인물·장소 등록 스키마."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.world import WORLD_ENTITY_KINDS

_NAME_MAX = 50
_KIND_MAX = 20
_HAIR_MAX = 200
_OUTFIT_MAX = 200
_AGE_RANGE_MAX = 50
_TEXT_FIELDS = ("name", "kind", "hair", "outfit", "age_range", "features")
_OPTIONAL_TEXT = ("hair", "outfit", "age_range", "features")


def _strip(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _blank_to_none(value: str | None) -> str | None:
    if value == "":
        return None
    return value


def _require_kind(value: str) -> str:
    if value not in WORLD_ENTITY_KINDS:
        raise ValueError("kind는 person 또는 place여야 합니다.")
    return value


class WorldEntityCreate(BaseModel):
    """외형 값은 번역하지 않고, 앞뒤 공백만 뺀 입력 그대로 저장한다."""

    name: str = Field(min_length=1, max_length=_NAME_MAX)
    kind: str = Field(min_length=1, max_length=_KIND_MAX)
    age_range: str | None = Field(default=None, max_length=_AGE_RANGE_MAX)
    hair: str | None = Field(default=None, max_length=_HAIR_MAX)
    outfit: str | None = Field(default=None, max_length=_OUTFIT_MAX)
    features: str | None = None

    @field_validator(*_TEXT_FIELDS, mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        return _strip(value)

    @field_validator(*_OPTIONAL_TEXT)
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        return _require_kind(value)


class WorldEntityUpdate(BaseModel):
    """보낸 칸만 바꾼다. 외형의 빈 문자열은 그 칸을 비운다."""

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    kind: str | None = Field(default=None, min_length=1, max_length=_KIND_MAX)
    age_range: str | None = Field(default=None, max_length=_AGE_RANGE_MAX)
    hair: str | None = Field(default=None, max_length=_HAIR_MAX)
    outfit: str | None = Field(default=None, max_length=_OUTFIT_MAX)
    features: str | None = None

    @field_validator(*_TEXT_FIELDS, mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        return _strip(value)

    @field_validator(*_OPTIONAL_TEXT)
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("name")
    @classmethod
    def _name_required_when_sent(cls, value: str | None) -> str:
        if not value:
            raise ValueError("이름은 비울 수 없습니다.")
        return value

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str | None) -> str:
        if not value:
            raise ValueError("kind는 person 또는 place여야 합니다.")
        return _require_kind(value)


class WorldEntityListQuery(BaseModel):
    kind: str | None = Field(default=None, max_length=_KIND_MAX)

    @field_validator("kind", mode="before")
    @classmethod
    def _strip_kind(cls, value: Any) -> Any:
        return _strip(value)

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value == "":
            raise ValueError("kind는 person 또는 place여야 합니다.")
        return _require_kind(value)


class WorldEntityResponse(BaseModel):
    id: int
    kind: str
    name: str
    age_range: str | None = None
    hair: str | None = None
    outfit: str | None = None
    features: str | None = None
    created_at: datetime


class WorldEntityListResponse(BaseModel):
    entities: list[WorldEntityResponse]
