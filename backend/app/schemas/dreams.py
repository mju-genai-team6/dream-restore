"""꿈 기록 생성·조회·원문 확정·음성 업로드·꿈 일기 목록 스키마."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.core.enums import DreamStatus, InputType
from app.schemas.jobs import JobSummary
from app.schemas.renders import RenderSummary
from app.services import mock_data


class DreamCreate(BaseModel):
    """텍스트 입력이면 text가 필요하고, 음성 입력이면 생성 후 음성을 따로 올린다."""

    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.DREAM_CREATE]})

    input_type: InputType
    text: str | None = Field(default=None, min_length=1, max_length=5000)

    @model_validator(mode="after")
    def _text_required_for_text_input(self) -> "DreamCreate":
        if self.input_type == InputType.TEXT and not self.text:
            raise PydanticCustomError("text_required", "텍스트로 기록할 때는 text가 필요합니다.")
        return self


class DreamStatusResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.DREAM_CREATED]})

    dream_id: int
    status: DreamStatus


class DreamConfirm(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.DREAM_CONFIRM]})

    confirmed_text: str = Field(min_length=1, max_length=5000)


class InterviewProgress(BaseModel):
    answered: int
    total: int


class DreamResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.DREAM]})

    dream_id: int
    status: DreamStatus
    input_type: InputType
    raw_text: str | None = None
    confirmed_text: str | None = None
    interview_progress: InterviewProgress
    active_job: JobSummary | None = None
    latest_render: RenderSummary | None = None
    created_at: datetime


class AudioUploadResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.AUDIO_UPLOADED]})

    audio_id: int
    transcript: str | None = Field(default=None, description="STT 변환 텍스트 (S2부터)")


class DreamListItem(BaseModel):
    dream_id: int
    created_at: datetime
    thumbnail_url: str | None = None
    summary: str | None = None
    status: DreamStatus


class DreamListResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.DREAM_LIST]})

    items: list[DreamListItem]
    next_cursor: str | None = Field(default=None, description="다음 페이지 커서. 없으면 마지막")
