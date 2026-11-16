"""작업 등록·조회·진행 상태 스키마."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.enums import FailureCode, JobStage, JobStatus, JobType
from app.services import mock_data


class JobCreate(BaseModel):
    """API로 직접 요청하는 작업은 장면 생성뿐이다. 이미지·영상 작업은 서버가 등록한다."""

    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.JOB_CREATE]})

    type: Literal[JobType.GENERATE_SCENES]


class JobCreateResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.JOB_CREATED]})

    job_id: int
    status: JobStatus


class JobSummary(BaseModel):
    """꿈 조회의 진행 중 작업, SSE 이벤트 data에 쓴다. 퍼센트 값은 두지 않는다."""

    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.JOB_EVENTS[1]]})

    job_id: int
    type: JobType
    status: JobStatus
    stage: JobStage | None = None


class JobError(BaseModel):
    code: FailureCode
    message: str


class JobResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [mock_data.JOB, mock_data.JOB_FAILED_EXAMPLE]}
    )

    job_id: int
    dream_id: int
    type: JobType
    status: JobStatus
    stage: JobStage | None = None
    error: JobError | None = None
    created_at: datetime
    updated_at: datetime
