"""되묻기 질문과 답변 (interview_questions)."""

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InterviewQuestion


def save_questions(db: Session, dream_id: int, questions: Sequence[Mapping]) -> list[InterviewQuestion]:
    """질문을 한 번에 저장한다.

    questions: D의 InterviewQuestion을 model_dump()한 dict ({"order", "question", "target_element"}).
    같은 꿈에 같은 order가 이미 있으면 UNIQUE 제약으로 IntegrityError가 난다.
    """
    rows = [
        InterviewQuestion(
            dream_id=dream_id,
            order=q["order"],
            text=q["question"],
            target_element=q.get("target_element"),
        )
        for q in questions
    ]
    db.add_all(rows)
    db.flush()
    return sorted(rows, key=lambda q: q.order)


def list_questions(db: Session, dream_id: int) -> list[InterviewQuestion]:
    """order 순서대로."""
    return list(
        db.scalars(select(InterviewQuestion).where(InterviewQuestion.dream_id == dream_id).order_by(InterviewQuestion.order))
    )


def save_answer(
    db: Session, dream_id: int, question_id: int, *, answer: str | None = None, skipped: bool = False
) -> InterviewQuestion | None:
    """답변 또는 "기억 안 남"(skipped=True)을 저장한다. 질문이 없거나 다른 꿈의 질문이면 None.

    다시 답하면 덮어쓴다. 건너뛰면 answer는 비운다.
    """
    question = db.get(InterviewQuestion, question_id)
    if question is None or question.dream_id != dream_id:
        return None
    question.skipped = skipped
    question.answer = None if skipped else answer
    db.flush()
    return question


class Progress(NamedTuple):
    answered: int  # 답변했거나 건너뛴 질문 수
    total: int


def get_progress(db: Session, dream_id: int) -> Progress:
    """인터뷰 진행 위치. answered, total = get_progress(...)로 풀어 쓸 수 있다."""
    done = (InterviewQuestion.answer.is_not(None)) | InterviewQuestion.skipped
    answered, total = db.execute(
        select(func.count().filter(done), func.count()).where(InterviewQuestion.dream_id == dream_id)
    ).one()
    return Progress(answered, total)
