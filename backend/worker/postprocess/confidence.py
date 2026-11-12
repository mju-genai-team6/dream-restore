"""장면 확신도 집계 모듈 (E1 담당).

규칙 (계획서 3.1 및 백엔드 5절 합의안):
- 입력 확신도: high(확실=2), medium(보통=1), low(흐릿=0)
- 시각 요소(person, place, object)만 평균 계산에 포함하고,
  감정(emotion)은 블러를 적용할 시각 요소가 아니므로 집계에서 제외한다.
- 평균값 기준 장면 단계 결정:
  - 평균 < 0.5         -> low (흐릿)
  - 0.5 <= 평균 < 1.5  -> medium (보통)
  - 평균 >= 1.5        -> high (확실)
- 확신도가 누락되거나 허용되지 않은 값이 들어오면 임의로 채우지 않고
  ConfidenceInputError(ValueError)를 발생시킨다.
- 장면 단계를 계산하더라도 원래 요소별 확신도 목록은 그대로 보존한다.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from app.core.enums import Confidence, ElementType

RULE_VERSION = "visual_mean_v1"

CONFIDENCE_SCORES: dict[Confidence, int] = {
    Confidence.HIGH: 2,
    Confidence.MEDIUM: 1,
    Confidence.LOW: 0,
}

VISUAL_ELEMENT_TYPES: frozenset[ElementType] = frozenset(
    {
        ElementType.PERSON,
        ElementType.PLACE,
        ElementType.OBJECT,
    }
)

LOW_UPPER_BOUND: float = 0.5
MEDIUM_UPPER_BOUND: float = 1.5


class ConfidenceInputError(ValueError):
    """확신도 입력이 누락되었거나 허용되지 않은 형식일 때 발생하는 예외."""


@dataclass(frozen=True)
class ElementConfidenceRecord:
    """개별 요소의 확신도 기록 (원본 보존용)."""

    type: ElementType
    confidence: Confidence
    name: str = ""
    id: int | None = None
    is_visual: bool = True
    score: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "confidence": self.confidence.value,
            "is_visual": self.is_visual,
            "score": self.score,
        }


@dataclass(frozen=True)
class SceneConfidenceResult:
    """장면 확신도 집계 결과와 상세 내역."""

    confidence_level: Confidence
    mean_score: float
    visual_element_count: int
    excluded_emotion_count: int
    elements: tuple[ElementConfidenceRecord, ...]
    rule_version: str = RULE_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence_level"] = self.confidence_level.value
        data["elements"] = [el.to_dict() for el in self.elements]
        return data


def parse_element_type(raw_type: Any) -> ElementType:
    """요소 종류(ElementType)를 검증하여 반환한다."""
    if isinstance(raw_type, ElementType):
        return raw_type
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ConfidenceInputError(f"요소 종류(type)가 누락되었거나 올바르지 않습니다: {raw_type!r}")
    try:
        return ElementType(raw_type.strip().lower())
    except ValueError as exc:
        raise ConfidenceInputError(f"허용되지 않는 요소 종류입니다: {raw_type!r}") from exc


def parse_confidence(raw_confidence: Any) -> Confidence:
    """확신도(Confidence) 값을 검증하여 반환한다."""
    if isinstance(raw_confidence, Confidence):
        return raw_confidence
    if raw_confidence is None or (isinstance(raw_confidence, str) and not raw_confidence.strip()):
        raise ConfidenceInputError("요소의 확신도(confidence)가 누락되었습니다.")
    if not isinstance(raw_confidence, str):
        raise ConfidenceInputError(f"허용되지 않는 확신도 형식입니다: {raw_confidence!r}")
    try:
        return Confidence(raw_confidence.strip().lower())
    except ValueError as exc:
        raise ConfidenceInputError(f"허용되지 않는 확신도 값입니다: {raw_confidence!r}") from exc


def score_for_confidence(confidence: Confidence | str) -> int:
    """확신도 단계를 점수(high=2, medium=1, low=0)로 변환한다."""
    parsed = parse_confidence(confidence)
    return CONFIDENCE_SCORES[parsed]


def level_for_mean_score(mean_score: float) -> Confidence:
    """시각 요소 평균 점수를 장면 확신도 단계로 변환한다.

    - 평균 < 0.5        -> low (흐릿)
    - 0.5 <= 평균 < 1.5 -> medium (보통)
    - 평균 >= 1.5       -> high (확실)
    """
    if mean_score < LOW_UPPER_BOUND:
        return Confidence.LOW
    if mean_score < MEDIUM_UPPER_BOUND:
        return Confidence.MEDIUM
    return Confidence.HIGH


def _extract_field(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _normalize_element(item: Any) -> ElementConfidenceRecord:
    if item is None:
        raise ConfidenceInputError("요소 항목이 비어 있습니다(None).")

    raw_type = _extract_field(item, "type")
    raw_conf = _extract_field(item, "confidence")
    raw_name = _extract_field(item, "name", "")
    raw_id = _extract_field(item, "id", None)

    el_type = parse_element_type(raw_type)
    confidence = parse_confidence(raw_conf)
    name = str(raw_name).strip() if raw_name is not None else ""
    el_id = int(raw_id) if raw_id is not None else None

    is_visual = el_type in VISUAL_ELEMENT_TYPES
    score = CONFIDENCE_SCORES[confidence] if is_visual else None

    return ElementConfidenceRecord(
        id=el_id,
        type=el_type,
        name=name,
        confidence=confidence,
        is_visual=is_visual,
        score=score,
    )


def _select_scene_elements(
    elements: Sequence[Any],
    scene_element_names: Sequence[str] | None = None,
) -> list[ElementConfidenceRecord]:
    if not elements:
        raise ConfidenceInputError("확신도를 계산할 요소 목록이 비어 있습니다.")

    normalized = [_normalize_element(item) for item in elements]

    if scene_element_names is None:
        return normalized

    cleaned_names = [str(n).strip() for n in scene_element_names if str(n).strip()]
    if not cleaned_names:
        raise ConfidenceInputError("장면에 연결된 요소 이름(element_names)이 비어 있습니다.")

    by_name: dict[str, list[ElementConfidenceRecord]] = {}
    for record in normalized:
        if record.name:
            by_name.setdefault(record.name, []).append(record)

    selected: list[ElementConfidenceRecord] = []
    missing: list[str] = []
    for target_name in cleaned_names:
        matched = by_name.get(target_name)
        if not matched:
            missing.append(target_name)
        else:
            selected.extend(matched)

    if missing:
        raise ConfidenceInputError(
            f"장면에 지정된 요소를 전체 요소 목록에서 찾을 수 없습니다: {', '.join(missing)}"
        )

    return selected


def aggregate_scene_confidence_detail(
    elements: Sequence[Mapping[str, Any] | Any],
    scene_element_names: Sequence[str] | None = None,
) -> SceneConfidenceResult:
    """장면의 요소 목록으로부터 장면 확신도 단계와 상세 집계 내역을 계산한다.

    Args:
        elements: 요소(dict 또는 객체) 시퀀스. 각 항목은 `type`과 `confidence`를 포함해야 한다.
        scene_element_names: 장면에 등장하는 요소 이름 목록(선택). 지정 시 해당 이름의 요소만 필터링한다.

    Returns:
        SceneConfidenceResult: 장면 확신도 단계, 평균 점수, 시각 요소 수, 보존된 요소별 확신도 목록.

    Raises:
        ConfidenceInputError: 요소가 비어 있거나, 확신도/타입이 누락·오류이거나, 시각 요소가 하나도 없을 때.
    """
    selected = _select_scene_elements(elements, scene_element_names=scene_element_names)

    visual_scores = [rec.score for rec in selected if rec.is_visual and rec.score is not None]
    emotion_count = sum(1 for rec in selected if not rec.is_visual)

    if not visual_scores:
        raise ConfidenceInputError(
            "장면에 시각 요소(person, place, object)가 없어 장면 확신도를 계산할 수 없습니다."
        )

    mean_score = sum(visual_scores) / len(visual_scores)
    level = level_for_mean_score(mean_score)

    return SceneConfidenceResult(
        confidence_level=level,
        mean_score=round(mean_score, 4),
        visual_element_count=len(visual_scores),
        excluded_emotion_count=emotion_count,
        elements=tuple(selected),
    )


def aggregate_scene_confidence(
    elements: Sequence[Mapping[str, Any] | Any],
    scene_element_names: Sequence[str] | None = None,
) -> Confidence:
    """장면의 요소 확신도를 집계하여 장면 전체의 확신도 단계(high / medium / low)를 반환한다."""
    return aggregate_scene_confidence_detail(
        elements,
        scene_element_names=scene_element_names,
    ).confidence_level
