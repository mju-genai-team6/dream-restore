"""영상 생성 요청·최신 영상 조회 (S3). 사용: B2, 연결: E1"""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import error_responses
from app.schemas.renders import RenderCreateResponse, RenderResponse
from app.services import renders as render_service

router = APIRouter(prefix="/dreams", tags=["renders"])


@router.post(
    "/{dream_id}/renders",
    response_model=RenderCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="영상 생성 요청 (진행 중이면 기존 작업을 202로 반환)",
    responses=error_responses(404, 409),
)
def create_render(
    dream_id: int,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> RenderCreateResponse:
    return render_service.create_render(db, dream_id, background_tasks)


@router.get(
    "/{dream_id}/renders/latest",
    response_model=RenderResponse,
    summary="최신 영상 조회 (검증 끝난 영상만, 반영된 장면 버전, is_latest)",
    responses=error_responses(404),
)
def get_latest_render(dream_id: int, db: Annotated[Session, Depends(get_db)]) -> RenderResponse:
    return render_service.get_latest_render(db, dream_id)
