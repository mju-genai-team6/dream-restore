"""(선택, S4) 장면 나레이션 (narrations).

음성 파일은 E2 generate_narration 핸들러가 storage/에 저장하고, 여기에는 상대 경로와 길이만 기록한다.
장면 버전 하나에 나레이션 하나다 (핸들러가 이미 있는 narration.mp3를 덮어쓰지 않음).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Narration, SceneVersion
from app.repositories import InvalidData


def get_narration(db: Session, scene_version_id: int) -> Narration | None:
    """장면 버전의 나레이션. 없으면 None."""
    return db.scalars(
        select(Narration).where(Narration.scene_version_id == scene_version_id).order_by(Narration.id).limit(1)
    ).first()


def add_narration(db: Session, scene_version_id: int, *, audio_path: str, duration: float | None) -> Narration:
    """나레이션 결과를 기록한다. E2 결과의 narration_path, duration_seconds를 그대로 넘긴다.

    - 이미 기록이 있으면 새로 만들지 않고 기존 행을 그대로 돌려준다 (재시도·후처리 중복 호출에도 한 행).
    - 장면 버전이 없거나 duration이 음수면 InvalidData.
    - audio_path는 상대 경로만 (DB CHECK, 절대 경로·`..`은 IntegrityError).
    """
    if db.get(SceneVersion, scene_version_id) is None:
        raise InvalidData("장면 버전이 없습니다.", {"scene_version_id": scene_version_id})
    if duration is not None and duration < 0:
        raise InvalidData("나레이션 길이는 0 이상이어야 합니다.", {"duration": duration})

    existing = get_narration(db, scene_version_id)
    if existing is not None:
        return existing
    narration = Narration(scene_version_id=scene_version_id, audio_path=audio_path, duration=duration)
    db.add(narration)
    db.flush()
    db.refresh(narration)
    return narration
