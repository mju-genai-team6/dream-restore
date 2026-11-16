# TODO(DB 담당): repositories.dreams 로 교체
"""꿈 기록·음성 파일 임시 저장소. db 세션은 받기만 하고 쓰지 않는다."""
from sqlalchemy.orm import Session

from app.core.enums import DreamStatus
from app.models.dream import AudioFile, Dream
from app.services.stubs import store


def create_dream(db: Session | None, *, input_type: str, raw_text: str | None) -> Dream:
    timestamp = store.now()
    dream = Dream(
        id=store.next_id("dream"),
        input_type=input_type,
        status=DreamStatus.RECORDED.value,
        raw_text=raw_text,
        confirmed_text=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    store.dreams[dream.id] = dream
    return dream


def get_dream(db: Session | None, dream_id: int) -> Dream | None:
    return store.dreams.get(dream_id)


def update_confirmed_text(db: Session | None, dream_id: int, confirmed_text: str | None) -> Dream:
    """None이면 확정 원문을 비운다 (음성을 다시 올렸을 때)."""
    dream = store.dreams[dream_id]
    dream.confirmed_text = confirmed_text
    dream.updated_at = store.now()
    return dream


# TODO(DB 담당): repositories.dreams.update_raw_text 로 교체 (requests.md 요청)
def update_raw_text(db: Session | None, dream_id: int, raw_text: str) -> Dream:
    dream = store.dreams[dream_id]
    dream.raw_text = raw_text
    dream.updated_at = store.now()
    return dream


def transition_status(db: Session | None, dream_id: int, status: str) -> Dream:
    dream = store.dreams[dream_id]
    dream.status = status
    dream.updated_at = store.now()
    return dream


def add_audio_file(
    db: Session | None,
    *,
    dream_id: int,
    path: str,
    mime_type: str,
    size: int,
    duration: float | None,
) -> AudioFile:
    audio = AudioFile(
        id=store.next_id("audio"),
        dream_id=dream_id,
        path=path,
        mime_type=mime_type,
        size=size,
        duration=duration,
        created_at=store.now(),
    )
    store.audio_files[audio.id] = audio
    return audio
