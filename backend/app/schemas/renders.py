"""영상 생성·최신 영상 조회 스키마."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.services import mock_data


class RenderCreateResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.RENDER_CREATED]})

    render_id: int
    job_id: int


class RenderSummary(BaseModel):
    """꿈 조회 응답에 넣는 최신 영상 요약."""

    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.LATEST_RENDER_SUMMARY]})

    render_id: int
    video_url: str
    is_latest: bool


class SceneVersionRef(BaseModel):
    scene_id: int
    version_no: int


class RenderResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.RENDER]})

    render_id: int
    video_url: str
    scene_versions: list[SceneVersionRef]
    is_latest: bool
    created_at: datetime
