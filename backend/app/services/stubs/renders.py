# TODO(DB 담당): repositories.renders 로 교체
"""최신 영상 임시 조회. db 세션은 받기만 하고 쓰지 않는다."""
from sqlalchemy.orm import Session

from app.models.scene import Render
from app.services.stubs import store


def get_latest_render(db: Session | None, dream_id: int) -> Render | None:
    rows = [render for render in store.renders.values() if render.dream_id == dream_id]
    if not rows:
        return None
    return max(rows, key=lambda render: (render.created_at, render.id))
