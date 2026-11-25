"""장면 목록 스키마.

B2가 목업 기준으로 화면을 만들고 있어 기존 필드는 이름과 의미를 바꾸지 않고 필드만 추가한다.
"""
from pydantic import BaseModel, ConfigDict

from app.core.enums import Confidence, ElementType, JobStatus
from app.schemas.jobs import JobSummary
from app.services import mock_data


class SceneElement(BaseModel):
    element_id: int
    name: str
    type: ElementType
    confidence: Confidence | None = None
    entity_id: int | None = None


class SceneItem(BaseModel):
    scene_id: int
    order: int
    summary_ko: str
    image_url: str | None = None
    version_no: int
    elements: list[SceneElement]
    status: JobStatus
    confidence_level: Confidence | None = None
    active_job: JobSummary | None = None


class SceneListResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.SCENES]})

    scenes: list[SceneItem]
