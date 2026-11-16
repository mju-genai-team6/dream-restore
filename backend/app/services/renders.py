"""영상 생성 요청·최신 영상 조회. 지금은 목업(mock_data)을 돌려준다."""
from app.schemas.renders import RenderCreateResponse, RenderResponse
from app.services import mock_data
from app.services.dreams import ensure_sample_dream


# TODO(C-S3-04): images_ready 검사, 장면 버전 고정 create_render, render_video 작업 등록
def create_render(dream_id: int) -> RenderCreateResponse:
    ensure_sample_dream(dream_id)
    return RenderCreateResponse.model_validate(mock_data.RENDER_CREATED)


# TODO(C-S3-04): get_latest_render, 검증 완료된 영상만 응답
def get_latest_render(dream_id: int) -> RenderResponse:
    ensure_sample_dream(dream_id)
    return RenderResponse.model_validate(mock_data.RENDER)
