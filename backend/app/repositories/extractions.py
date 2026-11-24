"""요소 추출 결과와 요소 (extractions, dream_elements)."""

from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Confidence, ElementType, ExtractionPhase
from app.models import DreamElement, Extraction, WorldEntity
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


def get_latest_extraction(
    db: Session, dream_id: int, phase: ExtractionPhase | str | None = None
) -> Extraction | None:
    """가장 최근 추출 1건. 없으면 None. phase를 주면 그 단계 중 최근 것.

    list_elements가 쓰는 추출과 같다 (꿈의 요소 목록은 가장 최근 추출 기준).
    """
    query = select(Extraction).where(Extraction.dream_id == dream_id)
    if phase is not None:
        query = query.where(Extraction.phase == str(phase))
    return db.scalar(query.order_by(Extraction.created_at.desc(), Extraction.id.desc()).limit(1))


def list_elements(db: Session, dream_id: int, phase: ExtractionPhase | str | None = None) -> list[DreamElement]:
    """가장 최근 추출의 요소 목록 (id 순서).

    phase를 주지 않으면 마지막 추출(인터뷰 후 재추출이 있으면 그것)을 쓴다.
    """
    latest = get_latest_extraction(db, dream_id, phase)
    if latest is None:
        return []
    extraction_id = latest.id
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


def set_character_appearances(db: Session, dream_id: int, characters: Sequence[Mapping]) -> list[DreamElement]:
    """인물 요소에 이미지용 영어 이름·외형을 저장한다 (C 요청, 장면 생성 성공 후 호출).

    characters: D의 SceneSplitResult.characters를 model_dump()한 dict 목록
                ({"name", "name_en", "appearance_en"}). name은 이 꿈의 최신 인물 요소 이름.
    하나라도 틀리면(이 꿈의 인물 요소가 아니거나 name_en이 비어 있음) InvalidData를 던지고 아무것도 바꾸지 않는다.
    다시 부르면 덮어쓴다 (장면을 다시 분할한 경우).
    """
    people = {e.name: e for e in list_elements(db, dream_id) if e.type == ElementType.PERSON.value}
    unknown = sorted({str(c.get("name", "")) for c in characters} - set(people))
    if unknown:
        raise InvalidData("이 꿈 기록의 인물 요소가 아닙니다.", {"names": unknown})
    empty = sorted(str(c["name"]) for c in characters if not str(c.get("name_en") or "").strip())
    if empty:
        raise InvalidData("name_en이 비어 있습니다.", {"names": empty})

    updated = []
    for c in characters:
        element = people[str(c["name"])]
        element.name_en = str(c["name_en"]).strip()
        element.appearance_en = str(c.get("appearance_en") or "").strip()
        updated.append(element)
    db.flush()
    return updated


def link_element_entity(db: Session, element_id: int, entity_id: int | None) -> DreamElement:
    """요소를 세계관 인물·장소(world_entities)에 연결한다 (C 요청). entity_id=None이면 연결을 푼다.

    요소가 없거나 세계관 항목이 없거나, 요소 종류와 세계관 종류가 다르면(person-person, place-place만 가능)
    InvalidData를 던지고 아무것도 바꾸지 않는다. flush까지 하고 commit은 C가 한다.
    """
    element = db.get(DreamElement, element_id)
    if element is None:
        raise InvalidData("요소를 찾을 수 없습니다.", {"element_id": element_id})
    if entity_id is not None:
        entity = db.get(WorldEntity, entity_id)
        if entity is None:
            raise InvalidData("세계관 항목을 찾을 수 없습니다.", {"entity_id": entity_id})
        if entity.kind != element.type:
            raise InvalidData(
                "요소 종류와 세계관 항목 종류가 다릅니다.",
                {"element_type": element.type, "entity_kind": entity.kind},
            )
    element.entity_id = entity_id
    db.flush()
    return element

