"""꿈 기록 처리. 생성·조회·원문 확정은 임시 저장소를 쓰고, 목록·음성은 아직 목업이다."""
from sqlalchemy.orm import Session

from app.core.enums import DreamStatus, InputType
from app.core.errors import InvalidState, NotFound
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


# TODO(C-S1-06): get_dream 결과로 존재 여부 확인
def ensure_sample_dream(dream_id: int) -> None:
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


# TODO(C-S1-06): 형식·크기 검사, paths.audio() 경로에 저장, add_audio_file
# TODO(C-S2-01): transcribe 호출 결과를 transcript로 응답
def upload_audio(dream_id: int) -> AudioUploadResponse:
    ensure_sample_dream(dream_id)
    return AudioUploadResponse.model_validate(mock_data.AUDIO_UPLOADED)


# TODO(C-S3-05): list_dreams 커서 페이지 조회
def list_dreams(cursor: str | None, limit: int) -> DreamListResponse:
    return DreamListResponse.model_validate(mock_data.DREAM_LIST)
