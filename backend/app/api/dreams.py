"""꿈 기록 생성·조회·원문 확정·음성 업로드 (S1) / 꿈 일기 목록 (S3). 사용: B1, B2"""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import mark_mock
from app.db.session import get_db
from app.schemas.common import error_responses
from app.schemas.dreams import (
    AudioUploadResponse,
    DreamConfirm,
    DreamCreate,
    DreamListResponse,
    DreamResponse,
    DreamStatusResponse,
)
from app.services import dreams as dream_service

router = APIRouter(prefix="/dreams", tags=["dreams"])


@router.post(
    "",
    response_model=DreamStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="꿈 기록 생성",
    responses=error_responses(400),
)
def create_dream(
    body: DreamCreate, db: Annotated[Session, Depends(get_db)]
) -> DreamStatusResponse:
    return dream_service.create_dream(db, body)


@router.get(
    "",
    response_model=DreamListResponse,
    summary="꿈 일기 목록 (커서 페이지)",
    responses=error_responses(400),
    dependencies=[Depends(mark_mock)],
)
def list_dreams(
    cursor: str | None = Query(default=None, description="이전 응답의 next_cursor"),
    limit: int = Query(default=20, ge=1, le=50),
) -> DreamListResponse:
    return dream_service.list_dreams(cursor, limit)


@router.get(
    "/{dream_id}",
    response_model=DreamResponse,
    summary="꿈 기록 조회 (상태, 원문, 인터뷰 진행, 진행 중 작업, 최신 영상)",
    responses=error_responses(404),
)
def get_dream(
    dream_id: int, db: Annotated[Session, Depends(get_db)]
) -> DreamResponse:
    return dream_service.get_dream(db, dream_id)


@router.patch(
    "/{dream_id}",
    response_model=DreamStatusResponse,
    summary="원문 확정",
    responses=error_responses(400, 404, 409),
)
def confirm_text(
    dream_id: int,
    body: DreamConfirm,
    db: Annotated[Session, Depends(get_db)],
) -> DreamStatusResponse:
    return dream_service.confirm_text(db, dream_id, body)


@router.post(
    "/{dream_id}/audio",
    response_model=AudioUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="음성 업로드 (webm·mp4·m4a, 최대 25MB)",
    responses=error_responses(400, 404, 409, 413, 415),
    dependencies=[Depends(mark_mock)],
)
def upload_audio(
    dream_id: int, file: Annotated[UploadFile, File(description="녹음 파일")]
) -> AudioUploadResponse:
    return dream_service.upload_audio(dream_id)
