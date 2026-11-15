"""질문 조회·답변 저장. 첫 조회 때 질문을 만들고, 이후에는 저장된 질문을 돌려준다."""
from sqlalchemy.orm import Session

from app.core.enums import DreamStatus, ExtractionPhase
from app.core.errors import InvalidState, NotFound
from app.llm.interview import extract_and_ask
from app.models.dream import Dream
from app.models.interview import InterviewQuestion
from app.schemas.interview import (
    AnswerCreate,
    AnswerResponse,
    InterviewQuestionItem,
    InterviewResponse,
)
from app.services.llm_calls import call_llm, dream_lock
from app.services.state_machine import ensure_transition
from app.services.stubs import dreams as dream_repo
from app.services.stubs import elements as element_repo
from app.services.stubs import interview as interview_repo
from app.services.transactions import commit, rollback


def require_dream(db: Session | None, dream_id: int) -> Dream:
    dream = dream_repo.get_dream(db, dream_id)
    if dream is None:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})
    return dream


def confirmed_text(dream: Dream) -> str:
    text = (dream.confirmed_text or "").strip()
    if not text:
        raise InvalidState("꿈 내용을 먼저 확정해 주세요.", {"status": dream.status})
    return text


def _is_answered(question: InterviewQuestion) -> bool:
    return question.answer is not None or question.skipped


def _interview_response(rows: list[InterviewQuestion]) -> InterviewResponse:
    items = [
        InterviewQuestionItem(
            question_id=row.id,
            order=row.order,
            target_element=row.target_element,
            question=row.text,
            answered=_is_answered(row),
            skipped=row.skipped,
        )
        for row in rows
    ]
    return InterviewResponse(
        questions=items, answered=sum(1 for item in items if item.answered), total=len(items)
    )


def get_interview(db: Session | None, dream_id: int) -> InterviewResponse:
    dream = require_dream(db, dream_id)
    rows = interview_repo.list_questions(db, dream_id)
    if rows:
        return _interview_response(rows)

    ensure_transition(DreamStatus(dream.status), DreamStatus.INTERVIEWING)
    text = confirmed_text(dream)
    with dream_lock(dream_id):
        rows = interview_repo.list_questions(db, dream_id)
        if rows:
            return _interview_response(rows)
        result = call_llm(
            extract_and_ask, text, failed_message="질문을 만들지 못했습니다. 다시 시도해 주세요."
        )
        # TODO(C-S2-06): 실제 DB에서 (dream_id, order) 중복 저장 충돌이 나면 rollback 후 저장된 질문을 다시 읽어 돌려준다
        try:
            element_repo.save_extraction(
                db,
                dream_id=dream_id,
                phase=ExtractionPhase.RAW.value,
                payload=result.model_dump(mode="json"),
                elements=[element.model_dump(mode="json") for element in result.elements],
                text_length=len(text),
            )
            rows = interview_repo.save_questions(
                db,
                dream_id,
                [
                    {"order": q.order, "text": q.question, "target_element": q.target_element}
                    for q in result.questions
                ],
            )
            dream_repo.transition_status(db, dream_id, DreamStatus.INTERVIEWING.value)
            commit(db)
        except Exception:
            rollback(db)
            raise
    return _interview_response(rows)


def save_answer(db: Session | None, dream_id: int, body: AnswerCreate) -> AnswerResponse:
    """답변 저장만 한다. 재추출은 요소 목록 조회(GET /elements) 때 한다."""
    dream = require_dream(db, dream_id)
    if DreamStatus(dream.status) != DreamStatus.INTERVIEWING:
        raise InvalidState("현재 단계에서는 답변을 저장할 수 없습니다.", {"status": dream.status})
    question_ids = {row.id for row in interview_repo.list_questions(db, dream_id)}
    if body.question_id not in question_ids:
        raise NotFound("질문을 찾을 수 없습니다.", {"question_id": body.question_id})

    # 재추출이 진행 중이면 끝날 때까지 기다린 뒤 아래 검사로 막는다
    with dream_lock(dream_id):
        latest = element_repo.get_latest_extraction(db, dream_id)
        if latest is not None and latest.phase == ExtractionPhase.AFTER_INTERVIEW.value:
            raise InvalidState(
                "답변을 반영한 요소 정리가 끝나 답변을 바꿀 수 없습니다.", {"status": dream.status}
            )
        try:
            interview_repo.save_answer(
                db,
                body.question_id,
                answer=None if body.skipped else body.answer,
                skipped=body.skipped,
            )
            commit(db)
        except Exception:
            rollback(db)
            raise
    answered, total = interview_repo.get_progress(db, dream_id)
    return AnswerResponse(remaining=total - answered, completed=answered == total)
