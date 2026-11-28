"""장면 목록 스키마.

B2가 목업 기준으로 화면을 만들고 있어 기존 필드는 이름과 의미를 바꾸지 않고 필드만 추가한다.
"""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    current_version_id: int


class SceneListResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.SCENES]})

    scenes: list[SceneItem]


class SceneRevisionCreate(BaseModel):
    """자연어 수정 요청. instruction은 앞뒤 공백을 뺀 뒤 1~200자여야 한다."""

    instruction: str = Field(min_length=1, max_length=200)
    base_version_id: int

    @field_validator("instruction", mode="before")
    @classmethod
    def _strip_instruction(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class SceneRevisionAccepted(BaseModel):
    """새 장면 버전과 그 버전의 이미지 작업. 나레이션 작업은 응답에 넣지 않는다."""

    scene_version_id: int
    job: JobSummary
