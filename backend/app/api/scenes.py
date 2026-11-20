"""장면 목록 (S3), 장면 수정 POST /scenes/{id}/revisions (S4 선택). 사용: B2"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import error_responses
from app.schemas.scenes import SceneListResponse
from app.services import scenes as scene_service

router = APIRouter(prefix="", tags=["scenes"])


@router.get(
    "/dreams/{dream_id}/scenes",
    response_model=SceneListResponse,
    summary="장면 목록 (순서, 요약, 이미지 주소, 버전, 상태, 장면 확신도, 요소 확신도, 진행 중 이미지 작업)",
    responses=error_responses(404),
)
def list_scenes(dream_id: int, db: Annotated[Session, Depends(get_db)]) -> SceneListResponse:
    return scene_service.list_scenes(db, dream_id)
