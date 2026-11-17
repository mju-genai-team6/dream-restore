"""음성 파일 기록 (audio_files). 파일 자체는 C가 storage/에 저장한다."""

from sqlalchemy.orm import Session

from app.models import AudioFile


def add_audio_file(
    db: Session,
    *,
    dream_id: int,
    path: str,
    mime_type: str,
    size: int,
    duration: float | None,
) -> AudioFile:
    """path는 storage/ 기준 상대 경로 (storage/paths.py audio())."""
    audio = AudioFile(dream_id=dream_id, path=path, mime_type=mime_type, size=size, duration=duration)
    db.add(audio)
    db.flush()
    db.refresh(audio)
    return audio
