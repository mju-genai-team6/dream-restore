"""장면 목록 스키마."""
from pydantic import BaseModel, ConfigDict

from app.core.enums import Confidence, ElementType
from app.services import mock_data


class SceneElement(BaseModel):
    name: str
    type: ElementType
    confidence: Confidence | None = None


class SceneItem(BaseModel):
    scene_id: int
    order: int
    summary_ko: str
    image_url: str | None = None
    version_no: int
    elements: list[SceneElement]


class SceneListResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.SCENES]})

    scenes: list[SceneItem]
