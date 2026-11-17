"""작업 등록·조회·진행 상태 스키마."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.enums import FailureCode, JobStage, JobStatus, JobType
from app.services import mock_data

# jobs.error_code의 CHECK 제약에 없는 값이라 DB에는 NULL로 두고 응답에서만 쓴다 (docs/rules/job-status.md)
INTERNAL_ERROR = "INTERNAL_ERROR"


class JobCreate(BaseModel):
    """API로 직접 요청하는 작업은 장면 생성뿐이다. 이미지·영상 작업은 서버가 등록한다."""

    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.JOB_CREATE]})

    type: Literal[JobType.GENERATE_SCENES]


class JobError(BaseModel):
    code: FailureCode | Literal["INTERNAL_ERROR"]
    message: str


class JobSummary(BaseModel):
    """작업 등록·조회 응답, 꿈 조회의 진행 중 작업, SSE 이벤트 data에 쓴다. 퍼센트 값은 두지 않는다."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [mock_data.JOB_QUEUED, mock_data.JOB, mock_data.JOB_FAILED_EXAMPLE]
        }
    )

    job_id: int
    type: JobType
    status: JobStatus
    stage: JobStage | None = None
    dream_id: int | None = None
    target_id: int | None = None
    attempt: int | None = None
    error: JobError | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
