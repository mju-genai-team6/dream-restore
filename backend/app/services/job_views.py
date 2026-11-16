"""jobs 행을 API 응답(JobSummary)으로 바꾼다. 실행기·꿈 조회·작업 API가 함께 쓴다."""
from app.core.enums import FailureCode, JobStage, JobStatus, JobType
from app.models import Job
from app.schemas.jobs import INTERNAL_ERROR, JobError, JobSummary


def _error(job: Job) -> JobError | None:
    if job.status != JobStatus.FAILED:
        return None
    # error_code가 NULL인 실패는 JobError가 아닌 예외로 끝난 작업이다
    code = FailureCode(job.error_code) if job.error_code else INTERNAL_ERROR
    return JobError(code=code, message=job.error_message or "")


def job_summary(job: Job) -> JobSummary:
    return JobSummary(
        job_id=job.id,
        type=JobType(job.type),
        status=JobStatus(job.status),
        stage=JobStage(job.stage) if job.stage else None,
        dream_id=job.dream_id,
        target_id=job.target_id,
        attempt=job.attempt,
        error=_error(job),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
