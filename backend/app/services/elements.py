"""요소 목록·확신도 저장. 지금은 목업(mock_data)을 돌려준다."""
from app.schemas.elements import ConfidenceUpdate, ElementListResponse
from app.services import mock_data
from app.services.dreams import ensure_sample_dream


# TODO(C-S2-03): list_elements 호출
def list_elements(dream_id: int) -> ElementListResponse:
    ensure_sample_dream(dream_id)
    return ElementListResponse.model_validate(mock_data.ELEMENTS)


# TODO(C-S2-03): 누락·잘못된 element_id 검사, set_confidences, commit
def set_confidences(dream_id: int, body: ConfidenceUpdate) -> ElementListResponse:
    """저장하지 않고, 요청한 확신도를 샘플 요소에 덮어써서 돌려준다."""
    ensure_sample_dream(dream_id)
    result = ElementListResponse.model_validate(mock_data.ELEMENTS)
    requested = {item.element_id: item.confidence for item in body.items}
    for element in result.elements:
        element.confidence = requested.get(element.element_id, element.confidence)
    return result
