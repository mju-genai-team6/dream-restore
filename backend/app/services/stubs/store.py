"""프로세스 메모리에 ORM 객체를 보관한다. 테스트마다 clear()로 비운다."""
from datetime import UTC, datetime

from app.models.dream import AudioFile, Dream
from app.models.interview import InterviewQuestion
from app.models.scene import Render

dreams: dict[int, Dream] = {}
audio_files: dict[int, AudioFile] = {}
questions: dict[int, InterviewQuestion] = {}
renders: dict[int, Render] = {}
_seq: dict[str, int] = {}


def next_id(kind: str) -> int:
    current = _seq.get(kind, 0) + 1
    _seq[kind] = current
    return current


def now() -> datetime:
    return datetime.now(UTC)


def clear() -> None:
    dreams.clear()
    audio_files.clear()
    questions.clear()
    renders.clear()
    _seq.clear()
