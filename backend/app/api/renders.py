"""영상 생성 요청·최신 영상 조회 (S3). 사용: B2, 연결: E1"""
from fastapi import APIRouter, Depends, status

from app.api.deps import mark_mock
from app.schemas.common import error_responses
from app.schemas.renders import RenderCreateResponse, RenderResponse
from app.services import renders as render_service

router = APIRouter(prefix="/dreams", tags=["renders"], dependencies=[Depends(mark_mock)])


@router.post(
    "/{dream_id}/renders",
    response_model=RenderCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="영상 생성 요청",
    responses=error_responses(404, 409),
)
def create_render(dream_id: int) -> RenderCreateResponse:
    return render_service.create_render(dream_id)


@router.get(
    "/{dream_id}/renders/latest",
    response_model=RenderResponse,
    summary="최신 영상 조회 (반영된 장면 버전, is_latest)",
    responses=error_responses(404),
)
def get_latest_render(dream_id: int) -> RenderResponse:
    return render_service.get_latest_render(dream_id)
