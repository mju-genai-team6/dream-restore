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


@dataclass(frozen=True)
class Character:
    """장면에 나오는 인물. appearance는 머리 모양, 머리색, 옷차림, 나이대, 구별되는 특징."""

    name: str
    appearance: str


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
