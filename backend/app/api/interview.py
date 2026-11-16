"""질문 조회·답변 저장 (S2). 사용: B1, 연결: D"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import error_responses
from app.schemas.interview import AnswerCreate, AnswerResponse, InterviewResponse
from app.services import interview as interview_service

router = APIRouter(prefix="/dreams", tags=["interview"])


# LLM을 요청 안에서 기다리므로 async def로 바꾸지 않는다 (이벤트 루프를 막음)
@router.get(
    "/{dream_id}/interview",
    response_model=InterviewResponse,
    summary="질문 조회 (첫 호출 시 5~7개 생성)",
    responses=error_responses(404, 409, 502, 504),
)
def get_interview(
    dream_id: int, db: Annotated[Session, Depends(get_db)]
) -> InterviewResponse:
    return interview_service.get_interview(db, dream_id)


@router.post(
    "/{dream_id}/interview",
    response_model=AnswerResponse,
    summary="답변 저장 (건너뛰기 포함)",
    responses=error_responses(400, 404, 409),
)
def save_answer(
    dream_id: int, body: AnswerCreate, db: Annotated[Session, Depends(get_db)]
) -> AnswerResponse:
    return interview_service.save_answer(db, dream_id, body)
