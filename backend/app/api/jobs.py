"""장면 생성 요청 POST /dreams/{id}/jobs, 작업 조회 GET /jobs/{id} (S2). 사용: B1, B2"""
from fastapi import APIRouter, Depends, status

from app.api.deps import mark_mock
from app.schemas.common import error_responses
from app.schemas.jobs import JobCreate, JobCreateResponse, JobResponse
from app.services import jobs as job_service

router = APIRouter(prefix="", tags=["jobs"], dependencies=[Depends(mark_mock)])


@router.post(
    "/dreams/{dream_id}/jobs",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="장면 생성 요청 (진행 중이면 기존 job_id)",
    responses=error_responses(400, 404, 409),
)
def create_job(dream_id: int, body: JobCreate) -> JobCreateResponse:
    return job_service.create_job(dream_id, body)


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="작업 조회 (상태, 단계, 실패 사유)",
    responses=error_responses(404),
)
def get_job(job_id: int) -> JobResponse:
    return job_service.get_job(job_id)
