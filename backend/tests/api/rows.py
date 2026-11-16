"""API가 저장한 행을 테스트에서 확인하는 조회 도우미 (read_db 세션에 쓴다)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AudioFile, DreamElement, Extraction, InterviewQuestion


def audio_files(db: Session) -> list[AudioFile]:
    return list(db.scalars(select(AudioFile).order_by(AudioFile.id)))


def extractions(db: Session) -> list[Extraction]:
    return list(db.scalars(select(Extraction).order_by(Extraction.id)))


def elements_of(db: Session, extraction_id: int) -> list[DreamElement]:
    return list(
        db.scalars(select(DreamElement).where(DreamElement.extraction_id == extraction_id).order_by(DreamElement.id))
    )


def questions(db: Session) -> list[InterviewQuestion]:
    return list(db.scalars(select(InterviewQuestion).order_by(InterviewQuestion.id)))
