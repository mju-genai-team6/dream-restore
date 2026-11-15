# TODO(DB 담당): repositories.interview 로 교체
"""되묻기 질문·답변·진행 위치 임시 저장소. db 세션은 받기만 하고 쓰지 않는다."""
from sqlalchemy.orm import Session

from app.models.interview import InterviewQuestion
from app.services.stubs import store


def save_questions(
    db: Session | None, dream_id: int, questions: list[dict]
) -> list[InterviewQuestion]:
    """questions의 각 항목: {"order", "text", "target_element"}. order 순으로 돌려준다."""
    timestamp = store.now()
    rows = []
    for item in questions:
        row = InterviewQuestion(
            id=store.next_id("question"),
            dream_id=dream_id,
            order=item["order"],
            text=item["text"],
            target_element=item.get("target_element"),
            answer=None,
            skipped=False,
            created_at=timestamp,
            updated_at=timestamp,
        )
        store.questions[row.id] = row
        rows.append(row)
    return sorted(rows, key=lambda row: row.order)


def list_questions(db: Session | None, dream_id: int) -> list[InterviewQuestion]:
    rows = [question for question in store.questions.values() if question.dream_id == dream_id]
    return sorted(rows, key=lambda row: row.order)


def save_answer(
    db: Session | None, question_id: int, *, answer: str | None, skipped: bool
) -> InterviewQuestion:
    question = store.questions[question_id]
    question.answer = answer
    question.skipped = skipped
    question.updated_at = store.now()
    return question


def get_progress(db: Session | None, dream_id: int) -> tuple[int, int]:
    """답변이 있거나 건너뛴 질문 수와 전체 질문 수를 돌려준다."""
    rows = [question for question in store.questions.values() if question.dream_id == dream_id]
    answered = sum(1 for question in rows if question.answer is not None or question.skipped)
    return answered, len(rows)
