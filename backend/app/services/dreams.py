"""꿈 기록 처리. 지금은 목업(mock_data)을 돌려준다."""
from app.core.errors import NotFound
from app.schemas.dreams import (
    AudioUploadResponse,
    DreamConfirm,
    DreamCreate,
    DreamListResponse,
    DreamResponse,
    DreamStatusResponse,
)
from app.services import mock_data


# TODO(C-S1-05): get_dream 결과로 존재 여부 확인
def ensure_sample_dream(dream_id: int) -> None:
    if dream_id != mock_data.DREAM_ID:
        raise NotFound("꿈 기록을 찾을 수 없습니다.", {"dream_id": dream_id})


# TODO(C-S1-05): create_dream 호출, commit
def create_dream(_: DreamCreate) -> DreamStatusResponse:
    return DreamStatusResponse.model_validate(mock_data.DREAM_CREATED)


# TODO(C-S1-05): get_dream, get_progress, 진행 중 작업, 최신 영상 조회
def get_dream(dream_id: int) -> DreamResponse:
    ensure_sample_dream(dream_id)
    return DreamResponse.model_validate(mock_data.DREAM)


# TODO(C-S1-05): ensure_transition 검사 후 update_confirmed_text, commit
def confirm_text(dream_id: int, _: DreamConfirm) -> DreamStatusResponse:
    ensure_sample_dream(dream_id)
    return DreamStatusResponse.model_validate(mock_data.DREAM_CONFIRMED)


# TODO(C-S1-06): 형식·크기 검사, paths.audio() 경로에 저장, add_audio_file
# TODO(C-S2-01): transcribe 호출 결과를 transcript로 응답
def upload_audio(dream_id: int) -> AudioUploadResponse:
    ensure_sample_dream(dream_id)
    return AudioUploadResponse.model_validate(mock_data.AUDIO_UPLOADED)


# TODO(C-S3-05): list_dreams 커서 페이지 조회
def list_dreams(cursor: str | None, limit: int) -> DreamListResponse:
    return DreamListResponse.model_validate(mock_data.DREAM_LIST)
