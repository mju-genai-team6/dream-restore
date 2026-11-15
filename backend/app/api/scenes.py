"""장면 목록 (S3), 장면 수정 POST /scenes/{id}/revisions (S4 선택). 사용: B2"""
from fastapi import APIRouter, Depends

from app.api.deps import mark_mock
from app.schemas.common import error_responses
from app.schemas.scenes import SceneListResponse
from app.services import scenes as scene_service

router = APIRouter(prefix="", tags=["scenes"], dependencies=[Depends(mark_mock)])


@router.get(
    "/dreams/{dream_id}/scenes",
    response_model=SceneListResponse,
    summary="장면 목록 (순서, 요약, 이미지 주소, 버전, 요소 확신도)",
    responses=error_responses(404, 409),
)
def list_scenes(dream_id: int) -> SceneListResponse:
    return scene_service.list_scenes(dream_id)
