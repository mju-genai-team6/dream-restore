"""영상 (renders). 렌더 시작 시 장면 버전 목록을 고정하고 이후 바꾸지 않는다."""

from collections.abc import Mapping
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import JobStatus
from app.models import Render, Scene
from app.repositories import InvalidData


def _current_version_ids(db: Session, dream_id: int) -> list[int | None]:
    return list(db.scalars(select(Scene.current_version_id).where(Scene.dream_id == dream_id).order_by(Scene.order)))


def create_render(db: Session, dream_id: int) -> Render:
    """지금 각 장면의 현재 버전을 장면 순서대로 고정해 렌더(queued)를 만든다.

    장면이 없거나 현재 버전이 없는 장면이 있으면 InvalidData.
    """
    version_ids = _current_version_ids(db, dream_id)
    if not version_ids or None in version_ids:
        raise InvalidData("영상으로 만들 장면 버전이 없습니다.", {"dream_id": dream_id})
    render = Render(dream_id=dream_id, scene_version_ids=version_ids)
    db.add(render)
    db.flush()
    db.refresh(render)
    return render


def complete_render(
    db: Session,
    render_id: int,
    *,
    video_path: str,
    width: int,
    height: int,
    duration: float,
    postprocess_settings: Mapping | None = None,
) -> Render | None:
    """검증까지 끝난 영상 결과를 저장하고 succeeded로 바꾼다. 렌더가 없으면 None.

    scene_version_ids는 바꾸지 않는다.
    """
    render = db.get(Render, render_id)
    if render is None:
        return None
    render.status = JobStatus.SUCCEEDED.value
    render.video_path = video_path
    render.width = width
    render.height = height
    render.duration = duration
    if postprocess_settings is not None:
        render.postprocess_settings = dict(postprocess_settings)
    db.flush()
    return render


def fail_render(db: Session, render_id: int) -> Render | None:
    """렌더를 failed로 바꾼다. 렌더가 없으면 None.

    이미 succeeded인 렌더는 바꾸지 않고 그대로 돌려준다 (완료된 영상을 실패로 덮지 않음).
    실패 사유는 jobs.error_code·error_message에 기록한다 (renders에는 사유 컬럼이 없음).
    """
    render = db.get(Render, render_id)
    if render is None:
        return None
    if render.status != JobStatus.SUCCEEDED.value:
        render.status = JobStatus.FAILED.value
        db.flush()
    return render


class LatestRender(NamedTuple):
    render: Render
    is_latest: bool  # 영상에 쓴 장면 버전이 지금 장면들의 현재 버전과 같으면 True


def get_latest_render(db: Session, dream_id: int) -> LatestRender | None:
    """가장 최근에 완료(succeeded)된 영상과 최신 여부. 완료된 영상이 없으면 None.

    장면을 수정해 현재 버전이 바뀌면 이전 영상의 is_latest는 False가 된다.
    """
    render = db.scalar(
        select(Render)
        .where(Render.dream_id == dream_id, Render.status == JobStatus.SUCCEEDED.value)
        .order_by(Render.created_at.desc(), Render.id.desc())
        .limit(1)
    )
    if render is None:
        return None
    return LatestRender(render, list(render.scene_version_ids) == _current_version_ids(db, dream_id))
