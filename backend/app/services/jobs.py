"""작업 등록·조회. 지금은 목업(mock_data)을 돌려준다."""
from app.core.errors import NotFound
from app.schemas.jobs import JobCreate, JobCreateResponse, JobResponse
from app.services import mock_data
from app.services.dreams import ensure_sample_dream


# TODO(C-S2-04): 상태 검사 후 create_job_or_get_active, 실행기에 등록
def create_job(dream_id: int, _: JobCreate) -> JobCreateResponse:
    ensure_sample_dream(dream_id)
    return JobCreateResponse.model_validate(mock_data.JOB_CREATED)


# TODO(C-S2-04): get_job 호출
def get_job(job_id: int) -> JobResponse:
    if job_id != mock_data.SCENES_JOB_ID:
        raise NotFound("작업을 찾을 수 없습니다.", {"job_id": job_id})
    return JobResponse.model_validate(mock_data.JOB)
