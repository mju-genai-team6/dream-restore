# TODO(DB 담당): repositories.elements 로 교체
"""요소 추출 결과·요소·확신도 임시 저장소. db 세션은 받기만 하고 쓰지 않는다."""
from sqlalchemy.orm import Session

from app.models.interview import DreamElement, Extraction
from app.services.stubs import store


def save_extraction(
    db: Session | None,
    *,
    dream_id: int,
    phase: str,
    payload: dict,
    elements: list[dict],
    text_length: int,
) -> Extraction:
    """추출 결과 1행과 요소 행을 함께 저장한다. elements의 각 항목: {"type", "name", "description"}."""
    timestamp = store.now()
    extraction = Extraction(
        id=store.next_id("extraction"),
        dream_id=dream_id,
        phase=phase,
        payload=payload,
        element_count=len(elements),
        text_length=text_length,
        created_at=timestamp,
    )
    store.extractions[extraction.id] = extraction
    for item in elements:
        element = DreamElement(
            id=store.next_id("element"),
            dream_id=dream_id,
            extraction_id=extraction.id,
            type=item["type"],
            name=item["name"],
            description=item.get("description", ""),
            confidence=None,
            entity_id=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        store.elements[element.id] = element
    return extraction


def get_latest_extraction(db: Session | None, dream_id: int) -> Extraction | None:
    rows = [row for row in store.extractions.values() if row.dream_id == dream_id]
    if not rows:
        return None
    return max(rows, key=lambda row: row.id)


def list_elements(db: Session | None, dream_id: int) -> list[DreamElement]:
    """가장 최근 추출(extraction_id가 가장 큰 것)의 요소만 id 순으로 돌려준다."""
    latest = get_latest_extraction(db, dream_id)
    if latest is None:
        return []
    rows = [row for row in store.elements.values() if row.extraction_id == latest.id]
    return sorted(rows, key=lambda row: row.id)


def set_confidences(db: Session | None, dream_id: int, confidences: dict[int, str]) -> list[DreamElement]:
    """{element_id: confidence}를 저장하고 최신 요소 목록을 돌려준다. id 검사는 services가 한다."""
    timestamp = store.now()
    for element_id, confidence in confidences.items():
        element = store.elements[element_id]
        element.confidence = confidence
        element.updated_at = timestamp
    return list_elements(db, dream_id)
