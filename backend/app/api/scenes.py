"""장면 목록 (S3), 장면 수정 POST /scenes/{id}/revisions (S4 선택). 사용: B2"""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import error_responses
from app.schemas.scenes import (
    SceneListResponse,
    SceneRevisionAccepted,
    SceneRevisionCreate,
)
from app.services import revisions as revision_service
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


@router.post(
    "/scenes/{scene_id}/revisions",
    response_model=SceneRevisionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="자연어로 장면 하나 수정 (설정으로 켜고, D의 revise_scene이 있을 때만)",
    responses=error_responses(400, 404, 409, 502, 504),
)
def create_revision(
    scene_id: int,
    body: SceneRevisionCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> SceneRevisionAccepted:
    return revision_service.create_revision(db, scene_id, body, background_tasks)
