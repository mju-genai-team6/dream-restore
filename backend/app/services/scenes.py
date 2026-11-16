"""장면 목록. 지금은 목업(mock_data)을 돌려준다."""
from app.schemas.scenes import SceneListResponse
from app.services import mock_data
from app.services.dreams import ensure_sample_dream


# TODO(C-S3-03): list_scenes 호출, 이미지 주소는 paths.public_url
def list_scenes(dream_id: int) -> SceneListResponse:
    ensure_sample_dream(dream_id)
    return SceneListResponse.model_validate(mock_data.SCENES)
