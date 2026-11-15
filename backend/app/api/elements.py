"""요소 목록·확신도 저장 (S2). 사용: B1"""
from fastapi import APIRouter, Depends

from app.api.deps import mark_mock
from app.schemas.common import error_responses
from app.schemas.elements import ConfidenceUpdate, ElementListResponse
from app.services import elements as element_service

router = APIRouter(prefix="/dreams", tags=["elements"], dependencies=[Depends(mark_mock)])


@router.get(
    "/{dream_id}/elements",
    response_model=ElementListResponse,
    summary="요소 목록 (인터뷰 반영)",
    responses=error_responses(404, 409),
)
def list_elements(dream_id: int) -> ElementListResponse:
    return element_service.list_elements(dream_id)


@router.put(
    "/{dream_id}/elements/confidence",
    response_model=ElementListResponse,
    summary="요소별 확신도 저장",
    responses=error_responses(400, 404, 409),
)
def set_confidences(dream_id: int, body: ConfidenceUpdate) -> ElementListResponse:
    return element_service.set_confidences(dream_id, body)
