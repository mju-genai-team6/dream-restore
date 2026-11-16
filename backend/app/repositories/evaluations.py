"""(선택, S4) 평가 응답 (evaluations)."""

from sqlalchemy.orm import Session

from app.models import Evaluation


def save_evaluation(
    db: Session, *, dream_id: int, kind: str, condition: str, score: int, render_id: int | None = None
) -> Evaluation:
    """5점 척도 응답 하나를 저장한다. score는 1~5 (DB CHECK)."""
    evaluation = Evaluation(dream_id=dream_id, render_id=render_id, kind=kind, condition=condition, score=score)
    db.add(evaluation)
    db.flush()
    db.refresh(evaluation)
    return evaluation
