"""요소 목록·확신도 저장 (S2). 사용: B1, 연결: D"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import error_responses
from app.schemas.elements import ConfidenceUpdate, ElementListResponse
from app.services import elements as element_service

router = APIRouter(prefix="/dreams", tags=["elements"])


# LLM을 요청 안에서 기다리므로 async def로 바꾸지 않는다 (이벤트 루프를 막음)
@router.get(
    "/{dream_id}/elements",
    response_model=ElementListResponse,
    summary="요소 목록 (인터뷰 완료 후 첫 호출 시 재추출)",
    responses=error_responses(404, 409, 502, 504),
)
def list_elements(
    dream_id: int, db: Annotated[Session, Depends(get_db)]
) -> ElementListResponse:
    return element_service.list_elements(db, dream_id)


@router.put(
    "/{dream_id}/elements/confidence",
    response_model=ElementListResponse,
    summary="요소별 확신도 저장 (일부만 보내도 됨)",
    responses=error_responses(400, 404, 409),
)
def set_confidences(
    dream_id: int, body: ConfidenceUpdate, db: Annotated[Session, Depends(get_db)]
) -> ElementListResponse:
    return element_service.set_confidences(db, dream_id, body)
