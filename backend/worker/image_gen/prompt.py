"""이미지 프롬프트 조합 (E2 계획서 3.1, 3.3).

조합 순서: 공통 화풍 → 장면 내용 → 인물 외형 특징 → 확신도 스타일
- 공통 화풍: 모든 장면에 같은 문구를 넣어 분위기를 통일한다.
- 인물 외형: 한 꿈 안에서 같은 인물은 모든 장면에 같은 외형 문구를 반복한다 (일관성 실험 조건 B).
- 확신도 스타일: 문구는 E1이 정하고, E2는 받은 문구를 맨 뒤에 붙이기만 한다.

순서·문구 형식은 D, E1과 확정한 뒤에는 이 파일에서만 수정한다.
"""
from __future__ import annotations

from dataclasses import dataclass

# 모든 장면에 공통으로 붙이는 꿈 분위기 문구
DEFAULT_STYLE = "dreamlike, soft lighting, gentle painterly texture"

# 영상은 16:9이고 E1 렌더링이 남는 부분을 여백(pad)으로 채우므로, 주요 대상을 가운데 둔다.
COMPOSITION = "wide landscape composition, main subject near the center"


# 세계관 인물(world_entities)의 외형 항목. B2 인물 등록 화면과 같은 항목이고, 이 순서로 문구를 만든다
WORLD_ENTITY_FIELDS = ("age_range", "hair", "outfit", "features")


@dataclass(frozen=True)
class Character:
    """장면에 나오는 인물. appearance는 머리 모양, 머리색, 옷차림, 나이대, 구별되는 특징."""

    name: str
    appearance: str

    @classmethod
    def from_world_entity(cls, name: str, extra: str | None = None, **fields: str | None) -> Character:
        """등록된 세계관 인물(world_entities 행)로 만든다. 다른 날의 꿈에도 같은 외형 문구가 들어간다.

        fields: age_range, hair, outfit, features (비어 있는 항목은 건너뜀)
        extra:  이번 꿈에서만 다른 점 (예: "wearing a raincoat today"). 등록 외형 뒤에 붙는다
        """
        unknown = set(fields) - set(WORLD_ENTITY_FIELDS)
        if unknown:
            raise ValueError(f"알 수 없는 외형 항목: {sorted(unknown)}")
        parts = [_clean(fields.get(key)) for key in WORLD_ENTITY_FIELDS]
        parts.append(_clean(extra))
        return cls(name=name, appearance=", ".join(p for p in parts if p))


def _clean(text: str | None) -> str:
    return " ".join((text or "").split()).strip().rstrip(".")


def build_prompt(
    scene_prompt: str,
    characters: list[Character] | None = None,
    style: str | None = None,
    confidence_style: str | None = None,
) -> str:
    parts = [f"Art style: {_clean(style) or DEFAULT_STYLE}, {COMPOSITION}."]
    parts.append(f"Scene: {_clean(scene_prompt)}.")

    described = [c for c in characters or [] if _clean(c.appearance)]
    if described:
        lines = "; ".join(f"{_clean(c.name)} - {_clean(c.appearance)}" for c in described)
        parts.append(f"Characters (keep the same appearance in every scene): {lines}.")

    if _clean(confidence_style):
        parts.append(f"Memory clarity: {_clean(confidence_style)}.")
    return " ".join(parts)
