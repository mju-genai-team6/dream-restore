"""꿈 기록 처리. 생성·조회·원문 확정·음성 저장은 임시 저장소를 쓰고, 목록과 음성 변환 텍스트는 아직 목업이다."""
from pathlib import Path, PurePath
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import DreamStatus, InputType
from app.core.errors import AudioTooLarge, InvalidState, NotFound, UnsupportedAudio
from app.models.dream import Dream
from app.models.scene import Render
from app.schemas.dreams import (
    AudioUploadResponse,
    DreamConfirm,
    DreamCreate,
    DreamListResponse,
    DreamResponse,
    DreamStatusResponse,
    InterviewProgress,
)
from app.schemas.renders import RenderSummary
from app.services import mock_data
from app.services.stubs import dreams as dream_repo
from app.services.stubs import interview as interview_repo
from app.services.stubs import renders as render_repo
from app.services.transactions import commit, rollback
from app.storage import paths

_AUDIO_CHUNK_BYTES = 64 * 1024
_MP4_EXTENSIONS = ("mp4", "m4a")
_AUDIO_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "audio/webm": ("webm",),
    "audio/mp4": _MP4_EXTENSIONS,
    "audio/x-m4a": _MP4_EXTENSIONS,
    "audio/m4a": _MP4_EXTENSIONS,
}
# audio_files.mime_type CHECK는 audio/m4a를 허용하지 않는다
_AUDIO_MIME_ALIASES = {"audio/m4a": "audio/x-m4a"}


def ensure_sample_dream(dream_id: int) -> None:
    """목업 엔드포인트용: dream_id=1 샘플만 있는 것으로 본다."""
    if dream_id != mock_data.DREAM_ID:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})


def _status_response(dream: Dream) -> DreamStatusResponse:
    return DreamStatusResponse(dream_id=dream.id, status=DreamStatus(dream.status))


def _latest_render(render: Render | None) -> RenderSummary | None:
    """영상 경로는 검증이 끝나 video_path가 있을 때만 주소로 바꾼다."""
    if render is None or render.video_path is None:
        return None
    # TODO(C-S3-04): current_version_id와 scene_version_ids를 비교해 is_latest 계산
    return RenderSummary(
        render_id=render.id,
        video_url=paths.public_url(render.video_path),
        is_latest=True,
    )


def create_dream(db: Session | None, body: DreamCreate) -> DreamStatusResponse:
    """텍스트 입력은 확정 원문까지 저장하고, 음성은 원문 확정을 남긴다."""
    try:
        dream = dream_repo.create_dream(
            db, input_type=body.input_type.value, raw_text=body.text
        )
        if body.input_type == InputType.TEXT and body.text is not None:
            dream = dream_repo.update_confirmed_text(db, dream.id, body.text)
        commit(db)
    except Exception:
        rollback(db)
        raise
    return _status_response(dream)


def get_dream(db: Session | None, dream_id: int) -> DreamResponse:
    dream = dream_repo.get_dream(db, dream_id)
    if dream is None:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})
    answered, total = interview_repo.get_progress(db, dream_id)
    # active_job은 generate_scenes·render_video 중 진행 중인 하나만 담는다.
    # 조회 함수가 생기기 전까지 null. generate_image 진행은 장면 목록과 SSE에서 보여 준다.
    return DreamResponse(
        dream_id=dream.id,
        status=DreamStatus(dream.status),
        input_type=InputType(dream.input_type),
        raw_text=dream.raw_text,
        confirmed_text=dream.confirmed_text,
        interview_progress=InterviewProgress(answered=answered, total=total),
        active_job=None,
        latest_render=_latest_render(render_repo.get_latest_render(db, dream_id)),
        created_at=dream.created_at,
    )


def confirm_text(db: Session | None, dream_id: int, body: DreamConfirm) -> DreamStatusResponse:
    dream = dream_repo.get_dream(db, dream_id)
    if dream is None:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})
    if DreamStatus(dream.status) != DreamStatus.RECORDED:
        raise InvalidState(
            "현재 단계에서는 원문을 확정할 수 없습니다.",
            {"status": dream.status},
        )
    try:
        dream = dream_repo.update_confirmed_text(db, dream_id, body.confirmed_text)
        commit(db)
    except Exception:
        rollback(db)
        raise
    return _status_response(dream)


def _audio_format(filename: str | None, content_type: str | None) -> tuple[str, str]:
    """(DB에 기록할 mime, 확장자). 허용하지 않는 형식·확장자 조합이면 415."""
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    ext = PurePath(filename or "").suffix.lstrip(".").lower()
    if ext not in _AUDIO_EXTENSIONS.get(mime, ()):
        raise UnsupportedAudio(
            "webm·mp4·m4a 음성 파일만 올릴 수 있습니다.",
            {"content_type": content_type, "filename": filename},
        )
    return _AUDIO_MIME_ALIASES.get(mime, mime), ext


def _copy_limited(src: BinaryIO, dst: Path, max_bytes: int) -> int:
    """청크 단위로 복사하며 바이트를 센다. 한도를 넘으면 그 자리에서 413."""
    size = 0
    with dst.open("wb") as out:
        while chunk := src.read(_AUDIO_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise AudioTooLarge(
                    f"음성 파일은 {settings.audio_max_mb}MB까지 올릴 수 있습니다.",
                    {"max_mb": settings.audio_max_mb},
                )
            out.write(chunk)
    return size


def upload_audio(
    db: Session | None,
    dream_id: int,
    *,
    filename: str | None,
    content_type: str | None,
    fileobj: BinaryIO,
) -> AudioUploadResponse:
    """recorded 상태의 음성 꿈에만 허용. 다시 올리면 새 파일·새 행으로 기록한다."""
    dream = dream_repo.get_dream(db, dream_id)
    if dream is None:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})
    if InputType(dream.input_type) != InputType.VOICE:
        raise InvalidState("텍스트로 기록한 꿈에는 음성을 올릴 수 없습니다.", {"input_type": dream.input_type})
    if DreamStatus(dream.status) != DreamStatus.RECORDED:
        raise InvalidState("현재 단계에서는 음성을 올릴 수 없습니다.", {"status": dream.status})
    mime, ext = _audio_format(filename, content_type)

    rel_path = paths.audio(dream_id, uuid4().hex, ext)
    final = settings.storage_path / rel_path
    part = final.with_name(f"{final.name}.part")
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = _copy_limited(fileobj, part, settings.audio_max_mb * 1024 * 1024)
        part.replace(final)
    except Exception:
        part.unlink(missing_ok=True)
        raise

    try:
        audio = dream_repo.add_audio_file(
            db, dream_id=dream_id, path=str(rel_path), mime_type=mime, size=size, duration=None
        )
        commit(db)
    except Exception:
        rollback(db)
        final.unlink(missing_ok=True)
        raise
    # TODO(C-S2-01): transcribe 호출 결과를 transcript로 응답
    return AudioUploadResponse(audio_id=audio.id, transcript=mock_data.RAW_TEXT)


# TODO(C-S3-05): list_dreams 커서 페이지 조회
def list_dreams(cursor: str | None, limit: int) -> DreamListResponse:
    return DreamListResponse.model_validate(mock_data.DREAM_LIST)
