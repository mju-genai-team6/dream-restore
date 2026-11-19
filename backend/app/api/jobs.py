"""장면 생성 요청 POST /dreams/{id}/jobs, 작업 조회 GET /jobs/{id} (S2). 사용: B1, B2"""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import error_responses
from app.schemas.jobs import JobCreate, JobSummary
from app.services import images as image_service
from app.services import jobs as job_service

router = APIRouter(prefix="", tags=["jobs"])


@router.post(
    "/dreams/{dream_id}/jobs",
    response_model=JobSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="장면 생성 요청 (진행 중이면 기존 작업을 202로 반환)",
    responses=error_responses(400, 404, 409),
)
def create_job(
    dream_id: int,
    body: JobCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> JobSummary:
    return job_service.create_job(db, dream_id, body, background_tasks)


@router.post(
    "/dreams/{dream_id}/images/retry",
    response_model=list[JobSummary],
    status_code=status.HTTP_202_ACCEPTED,
    summary="이미지가 없는 장면의 이미지 다시 생성 (scenes_ready일 때, 진행 중이면 기존 작업 반환)",
    responses=error_responses(404, 409),
)
def retry_images(
    dream_id: int,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> list[JobSummary]:
    return image_service.retry_images(db, dream_id, background_tasks)


@router.get(
    "/jobs/{job_id}",
    response_model=JobSummary,
    summary="작업 조회 (상태, 단계, 시도 횟수, 실패 사유)",
    responses=error_responses(404),
)
def get_job(job_id: int, db: Annotated[Session, Depends(get_db)]) -> JobSummary:
    return job_service.get_job(db, job_id)
