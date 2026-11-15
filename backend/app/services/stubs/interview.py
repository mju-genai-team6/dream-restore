# TODO(DB 담당): repositories.interview 로 교체
"""인터뷰 진행 위치 임시 조회. db 세션은 받기만 하고 쓰지 않는다."""
from sqlalchemy.orm import Session

from app.services.stubs import store


def get_progress(db: Session | None, dream_id: int) -> tuple[int, int]:
    """답변이 있거나 건너뛴 질문 수와 전체 질문 수를 돌려준다."""
    rows = [question for question in store.questions.values() if question.dream_id == dream_id]
    answered = sum(1 for question in rows if question.answer is not None or question.skipped)
    return answered, len(rows)
