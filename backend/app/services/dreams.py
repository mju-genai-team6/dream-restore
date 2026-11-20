"""꿈 기록 처리. 생성·조회·원문 확정·음성 저장·STT·꿈 일기 목록."""
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import DreamStatus, InputType, JobType
from app.core.errors import (
    AudioTooLarge,
    InvalidState,
    NotFound,
    SttFailed,
    UnsupportedAudio,
    ValidationFailed,
)
from app.llm.interview import transcribe
from app.models.dream import Dream
from app.repositories import audio as audio_repo
from app.repositories import dreams as dream_repo
from app.repositories import interview as interview_repo
from app.repositories import jobs as job_repo
from app.repositories import renders as render_repo
from app.repositories import scenes as scene_repo
from app.repositories.renders import LatestRender
from app.schemas.dreams import (
    AudioUploadResponse,
    DreamConfirm,
    DreamCreate,
    DreamListItem,
    DreamListResponse,
    DreamResponse,
    DreamStatusResponse,
    InterviewProgress,
)
from app.schemas.renders import RenderSummary
from app.services import mock_data
from app.services.job_views import job_summary
from app.services.llm_calls import STT_FAILED_MESSAGE, call_stt, dream_lock
from app.services.scenes import image_url
from app.services.transactions import commit, expire_loaded, rollback
from app.storage import paths

_AUDIO_CHUNK_BYTES = 64 * 1024
_ALLOWED_AUDIO_MIMES = frozenset({"audio/webm", "audio/mp4", "audio/x-m4a", "audio/m4a"})
_M4A_MIMES = frozenset({"audio/x-m4a", "audio/m4a"})
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
_MP4_MAGIC = b"ftyp"  # 4번째 바이트부터
_MAGIC_BYTES = 8
_DREAM_JOB_TYPES = frozenset({JobType.GENERATE_SCENES, JobType.RENDER_VIDEO})
_SUMMARY_PREVIEW_CHARS = 60


def ensure_sample_dream(dream_id: int) -> None:
    """목업 엔드포인트용: dream_id=1 샘플만 있는 것으로 본다."""
    if dream_id != mock_data.DREAM_ID:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})


def _status_response(dream: Dream) -> DreamStatusResponse:
    return DreamStatusResponse(dream_id=dream.id, status=DreamStatus(dream.status))


def _latest_render(latest: LatestRender | None) -> RenderSummary | None:
    """완료된 영상 중 가장 최근 것. 영상 경로는 검증이 끝나 video_path가 있을 때만 주소로 바꾼다."""
    if latest is None or latest.render.video_path is None:
        return None
    return RenderSummary(
        render_id=latest.render.id,
        video_url=paths.public_url(latest.render.video_path),
        is_latest=latest.is_latest,
    )


def create_dream(db: Session, body: DreamCreate) -> DreamStatusResponse:
    """텍스트 입력은 확정 원문까지 저장하고, 음성은 원문 확정을 남긴다."""
    try:
        dream = dream_repo.create_dream(
            db, input_type=body.input_type.value, raw_text=body.text
        )
        if body.input_type == InputType.TEXT and body.text is not None:
            dream_repo.update_confirmed_text(db, dream.id, body.text)
        commit(db)
    except Exception:
        rollback(db)
        raise
    return _status_response(dream)


def get_dream(db: Session, dream_id: int) -> DreamResponse:
    dream = dream_repo.get_dream(db, dream_id)
    if dream is None:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})
    answered, total = interview_repo.get_progress(db, dream_id)
    # active_job은 generate_scenes·render_video 중 진행 중인 하나만 담는다.
    # generate_image 진행은 장면 목록과 SSE에서 보여 준다.
    # repositories의 정렬 순서에 기대지 않고 (created_at, id)가 가장 큰 작업을 고른다
    active_job = max(
        (job for job in job_repo.get_active_jobs(db, dream_id) if job.type in _DREAM_JOB_TYPES),
        key=lambda job: (job.created_at, job.id),
        default=None,
    )
    return DreamResponse(
        dream_id=dream.id,
        status=DreamStatus(dream.status),
        input_type=InputType(dream.input_type),
        raw_text=dream.raw_text,
        confirmed_text=dream.confirmed_text,
        interview_progress=InterviewProgress(answered=answered, total=total),
        active_job=None if active_job is None else job_summary(active_job),
        latest_render=_latest_render(render_repo.get_latest_render(db, dream_id)),
        created_at=dream.created_at,
    )


def confirm_text(db: Session, dream_id: int, body: DreamConfirm) -> DreamStatusResponse:
    dream = dream_repo.get_dream(db, dream_id)
    if dream is None:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})
    if DreamStatus(dream.status) != DreamStatus.RECORDED:
        raise InvalidState(
            "현재 단계에서는 원문을 확정할 수 없습니다.",
            {"status": dream.status},
        )
    try:
        dream_repo.update_confirmed_text(db, dream_id, body.confirmed_text)
        commit(db)
    except Exception:
        rollback(db)
        raise
    return _status_response(dream)


def _unsupported_audio(filename: str | None, content_type: str | None) -> UnsupportedAudio:
    return UnsupportedAudio(
        "webm·mp4·m4a 음성 파일만 올릴 수 있습니다.",
        {"content_type": content_type, "filename": filename},
    )


def _detect_format(head: bytes, declared_mime: str) -> tuple[str, str] | None:
    """파일 앞부분으로 (DB에 기록할 mime, 확장자)를 정한다. 판별되지 않으면 None.

    Whisper는 확장자로 형식을 판단하므로 클라이언트 파일 이름은 쓰지 않는다
    (Safari는 mp4로 녹음해도 이름이 .webm일 수 있다). mp4 계열에서 m4a인지만 content-type을 따른다.
    """
    if len(head) < _MAGIC_BYTES:
        return None
    if head.startswith(_WEBM_MAGIC):
        return "audio/webm", "webm"
    if head[4:8] == _MP4_MAGIC:
        # audio_files.mime_type CHECK는 audio/m4a를 허용하지 않는다
        if declared_mime in _M4A_MIMES:
            return "audio/x-m4a", "m4a"
        return "audio/mp4", "mp4"
    return None


def _copy_audio(
    src: BinaryIO, dst: Path, max_bytes: int, declared_mime: str
) -> tuple[int, tuple[str, str] | None]:
    """청크 단위로 복사하며 바이트를 센다. 형식은 첫 청크로 판별하고, 판별되지 않으면 바로 멈추고 None.
    한도를 넘으면 그 자리에서 413."""
    size = 0
    audio_format: tuple[str, str] | None = None
    with dst.open("wb") as out:
        while chunk := src.read(_AUDIO_CHUNK_BYTES):
            if audio_format is None:
                audio_format = _detect_format(chunk, declared_mime)
                if audio_format is None:
                    return size, None
            size += len(chunk)
            if size > max_bytes:
                raise AudioTooLarge(
                    f"음성 파일은 {settings.audio_max_mb}MB까지 올릴 수 있습니다.",
                    {"max_mb": settings.audio_max_mb},
                )
            out.write(chunk)
    return size, audio_format


def _require_uploadable(db: Session, dream_id: int) -> Dream:
    dream = dream_repo.get_dream(db, dream_id)
    if dream is None:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})
    if InputType(dream.input_type) != InputType.VOICE:
        raise InvalidState("텍스트로 기록한 꿈에는 음성을 올릴 수 없습니다.", {"input_type": dream.input_type})
    if DreamStatus(dream.status) != DreamStatus.RECORDED:
        raise InvalidState("현재 단계에서는 음성을 올릴 수 없습니다.", {"status": dream.status})
    return dream


def upload_audio(
    db: Session,
    dream_id: int,
    *,
    filename: str | None,
    content_type: str | None,
    fileobj: BinaryIO,
) -> AudioUploadResponse:
    """recorded 상태의 음성 꿈에만 허용. 다시 올리면 새 파일·새 행으로 기록하고 확정 원문을 비운다.

    STT가 실패해도 음성 파일·기록은 남는다. 다시 시도는 같은 엔드포인트로 다시 올린다.
    """
    _require_uploadable(db, dream_id)
    declared_mime = (content_type or "").split(";", 1)[0].strip().lower()
    if declared_mime not in _ALLOWED_AUDIO_MIMES:
        raise _unsupported_audio(filename, content_type)

    file_id = uuid4().hex
    part = settings.storage_path / paths.audio(dream_id, file_id, "part")
    part.parent.mkdir(parents=True, exist_ok=True)
    try:
        size, audio_format = _copy_audio(
            fileobj, part, settings.audio_max_mb * 1024 * 1024, declared_mime
        )
        if audio_format is None:
            raise _unsupported_audio(filename, content_type)
        mime, ext = audio_format
        rel_path = paths.audio(dream_id, file_id, ext)
        final = settings.storage_path / rel_path
        part.replace(final)
    except Exception:
        part.unlink(missing_ok=True)
        raise

    with dream_lock(dream_id):
        try:
            # 잠금을 기다리는 동안 인터뷰가 시작됐을 수 있어 DB에서 다시 읽는다
            expire_loaded(db)
            _require_uploadable(db, dream_id)
            audio = audio_repo.add_audio_file(
                db, dream_id=dream_id, path=str(rel_path), mime_type=mime, size=size, duration=None
            )
            dream_repo.update_confirmed_text(db, dream_id, None)
            commit(db)
        except Exception:
            rollback(db)
            final.unlink(missing_ok=True)
            raise

        # 음성 기록과 확정 원문 비우기는 위에서 commit했다. Session.rollback()은 마지막 commit 이후만
        # 되돌리므로 아래 STT나 raw_text 저장이 실패해도 그 기록은 남는다
        text = call_stt(transcribe, str(final.resolve())).strip()
        if not text:
            raise SttFailed(STT_FAILED_MESSAGE)
        try:
            dream_repo.update_raw_text(db, dream_id, text)
            commit(db)
        except Exception:
            rollback(db)
            raise
    return AudioUploadResponse(audio_id=audio.id, transcript=text)


def _text_preview(dream: Dream) -> str | None:
    text = " ".join((dream.confirmed_text or dream.raw_text or "").split())
    if not text:
        return None
    if len(text) > _SUMMARY_PREVIEW_CHARS:
        return text[:_SUMMARY_PREVIEW_CHARS] + "…"
    return text


def _list_item(db: Session, dream: Dream) -> DreamListItem:
    """첫 장면은 order가 가장 작은 장면. 장면·영상은 꿈마다 한 번씩만 읽는다."""
    scenes = scene_repo.list_scenes(db, dream.id)
    first = scenes[0].current_version if scenes else None
    latest = render_repo.get_latest_render(db, dream.id)
    return DreamListItem(
        dream_id=dream.id,
        created_at=dream.created_at,
        thumbnail_url=image_url(first) if first is not None else None,
        summary=first.summary_ko if first is not None else _text_preview(dream),
        status=DreamStatus(dream.status),
        input_type=InputType(dream.input_type),
        has_video=_latest_render(latest) is not None,
    )


def list_dreams(db: Session, cursor: str | None, limit: int) -> DreamListResponse:
    """최신순 커서 페이지. repositories의 cursor는 int이고 API는 str로 주고받는다."""
    if cursor is not None and not cursor.isdigit():
        raise ValidationFailed("cursor가 올바르지 않습니다.", {"cursor": cursor})
    page = dream_repo.list_dreams(db, None if cursor is None else int(cursor), limit)
    return DreamListResponse(
        items=[_list_item(db, item.dream) for item in page.items],
        next_cursor=None if page.next_cursor is None else str(page.next_cursor),
    )
