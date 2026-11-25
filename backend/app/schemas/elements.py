"""요소 목록·확신도 저장 스키마."""
from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Confidence, ElementType
from app.services import mock_data


class ElementItem(BaseModel):
    element_id: int
    type: ElementType
    name: str
    description: str = ""
    confidence: Confidence | None = Field(default=None, description="입력 전이면 null")
    entity_id: int | None = Field(default=None, description="연결된 세계관 항목. 없으면 null")


class ElementListResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.ELEMENTS]})

    elements: list[ElementItem]


class ConfidenceItem(BaseModel):
    element_id: int
    confidence: Confidence


class ConfidenceUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.CONFIDENCE_UPDATE]})

    items: list[ConfidenceItem] = Field(min_length=1)
