"""꿈 기록 (dreams)."""

from typing import NamedTuple

from sqlalchemy import select, tuple_, update
from sqlalchemy.orm import Session

from app.core.enums import DreamStatus
from app.models import Dream, Scene, SceneVersion


def create_dream(db: Session, *, input_type: str, raw_text: str | None) -> Dream:
    """status는 recorded로 시작한다."""
    dream = Dream(input_type=input_type, raw_text=raw_text)
    db.add(dream)
    db.flush()
    db.refresh(dream)  # status·created_at 등 DB 기본값 읽기
    return dream


def get_dream(db: Session, dream_id: int) -> Dream | None:
    return db.get(Dream, dream_id)


def update_confirmed_text(db: Session, dream_id: int, confirmed_text: str) -> Dream | None:
    """원문 확정. 꿈 기록이 없으면 None. 상태 검사는 C(services)가 한다."""
    dream = db.get(Dream, dream_id)
    if dream is None:
        return None
    dream.confirmed_text = confirmed_text
    db.flush()
    return dream


def transition_status(db: Session, dream_id: int, from_: DreamStatus | str, to: DreamStatus | str) -> bool:
    """현재 상태가 from_일 때만 to로 바꾸고, 바꿨으면 True.

    WHERE status = from_ 조건으로 한 번에 바꾸므로 두 요청이 동시에 와도 한 번만 성공한다.
    전이 규칙(어느 상태에서 어디로 갈 수 있는지)은 C의 services/state_machine.py가 검사한다.
    """
    result = db.execute(
        update(Dream)
        .where(Dream.id == dream_id, Dream.status == str(from_))
        .values(status=str(to))
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


class DreamListItem(NamedTuple):
    dream: Dream
    thumbnail_path: str | None  # 첫 장면 현재 버전의 이미지 (storage/ 기준 상대 경로)
    summary: str | None  # 첫 장면 현재 버전의 요약


class DreamPage(NamedTuple):
    items: list[DreamListItem]
    next_cursor: int | None  # 다음 페이지에 넘길 cursor. 없으면 마지막 페이지


def list_dreams(db: Session, cursor: int | None = None, limit: int = 20) -> DreamPage:
    """꿈 일기 목록. 최신순(created_at, id 내림차순).

    cursor는 앞 페이지의 next_cursor(마지막 꿈 기록 id). 처음에는 None.
    대표 이미지·요약은 첫 장면(order=1)의 현재 버전에서 가져오고, 장면이 아직 없으면 None.
    """
    query = (
        select(Dream, SceneVersion.image_path, SceneVersion.summary_ko)
        .outerjoin(Scene, (Scene.dream_id == Dream.id) & (Scene.order == 1))
        .outerjoin(SceneVersion, SceneVersion.id == Scene.current_version_id)
        .order_by(Dream.created_at.desc(), Dream.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        anchor = select(Dream.created_at, Dream.id).where(Dream.id == cursor).subquery()
        query = query.where(
            tuple_(Dream.created_at, Dream.id) < select(anchor.c.created_at, anchor.c.id).scalar_subquery()
        )

    rows = db.execute(query).all()
    items = [DreamListItem(dream, image_path, summary) for dream, image_path, summary in rows[:limit]]
    next_cursor = items[-1].dream.id if len(rows) > limit else None
    return DreamPage(items, next_cursor)
