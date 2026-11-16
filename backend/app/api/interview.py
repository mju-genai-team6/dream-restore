"""질문 조회·답변 저장 (S2). 사용: B1, 연결: D"""
from fastapi import APIRouter, Depends

from app.api.deps import mark_mock
from app.schemas.common import error_responses
from app.schemas.interview import AnswerCreate, AnswerResponse, InterviewResponse
from app.services import interview as interview_service

router = APIRouter(prefix="/dreams", tags=["interview"], dependencies=[Depends(mark_mock)])


@router.get(
    "/{dream_id}/interview",
    response_model=InterviewResponse,
    summary="질문 조회 (첫 호출 시 5~7개 생성)",
    responses=error_responses(404, 409),
)
def get_interview(dream_id: int) -> InterviewResponse:
    return interview_service.get_interview(dream_id)


@router.post(
    "/{dream_id}/interview",
    response_model=AnswerResponse,
    summary="답변 저장 (건너뛰기 포함)",
    responses=error_responses(400, 404, 409),
)
def save_answer(dream_id: int, body: AnswerCreate) -> AnswerResponse:
    return interview_service.save_answer(dream_id, body)
