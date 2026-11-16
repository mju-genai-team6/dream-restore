"""요소 추출 결과와 요소 (extractions, dream_elements)."""

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Confidence, ExtractionPhase
from app.models import DreamElement, Extraction
from app.repositories import InvalidData


def save_extraction(
    db: Session, dream_id: int, phase: ExtractionPhase | str, payload: Mapping, text_length: int
) -> Extraction:
    """LLM 추출 결과를 그대로 남기고, payload["elements"]로 요소 행을 만든다.

    payload: D의 ExtractionResult·ReextractionResult를 model_dump()한 dict.
    text_length: 추출에 쓴 텍스트 글자 수 (인터뷰 전후 지표, D).
    요소의 확신도는 비워 둔다 (사용자 입력만 저장).
    """
    elements = list(payload.get("elements", []))
    extraction = Extraction(
        dream_id=dream_id,
        phase=str(phase),
        payload=dict(payload),
        element_count=len(elements),
        text_length=text_length,
    )
    db.add(extraction)
    db.flush()
    db.add_all(
        DreamElement(
            dream_id=dream_id,
            extraction_id=extraction.id,
            type=e["type"],
            name=e["name"],
            description=e.get("description", ""),
        )
        for e in elements
    )
    db.flush()
    return extraction


def _latest_extraction_id(db: Session, dream_id: int, phase: ExtractionPhase | str | None) -> int | None:
    query = select(Extraction.id).where(Extraction.dream_id == dream_id)
    if phase is not None:
        query = query.where(Extraction.phase == str(phase))
    return db.scalar(query.order_by(Extraction.created_at.desc(), Extraction.id.desc()).limit(1))


def list_elements(db: Session, dream_id: int, phase: ExtractionPhase | str | None = None) -> list[DreamElement]:
    """가장 최근 추출의 요소 목록 (id 순서).

    phase를 주지 않으면 마지막 추출(인터뷰 후 재추출이 있으면 그것)을 쓴다.
    """
    extraction_id = _latest_extraction_id(db, dream_id, phase)
    if extraction_id is None:
        return []
    return list(
        db.scalars(select(DreamElement).where(DreamElement.extraction_id == extraction_id).order_by(DreamElement.id))
    )


def set_confidences(db: Session, dream_id: int, confidences: Mapping[int, Confidence | str]) -> list[DreamElement]:
    """요소별 확신도를 한 번에 저장한다 ({element_id: "high" | "medium" | "low"}).

    하나라도 틀리면(이 꿈의 최신 요소가 아니거나 값이 잘못됨) InvalidData를 던지고 아무것도 바꾸지 않는다.
    """
    allowed = {c.value for c in Confidence}
    bad_values = {eid: value for eid, value in confidences.items() if str(value) not in allowed}
    if bad_values:
        raise InvalidData("확신도 값이 올바르지 않습니다.", {"invalid_values": bad_values})

    elements = {e.id: e for e in list_elements(db, dream_id)}
    unknown = sorted(set(confidences) - set(elements))
    if unknown:
        raise InvalidData("이 꿈 기록의 요소가 아닙니다.", {"element_ids": unknown})

    for element_id, value in confidences.items():
        elements[element_id].confidence = str(value)
    db.flush()
    return [elements[element_id] for element_id in sorted(confidences)]
