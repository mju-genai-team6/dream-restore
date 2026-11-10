"""LLM 출력 스키마 (D 담당).

LLM이 돌려준 JSON이 이 모양과 맞는지 Pydantic으로 검사합니다.
맞지 않으면 최대 2회 다시 요청하고, 그래도 실패하면 예외를 던집니다 (app/llm/README.md).

- 예시 JSON: docs/schemas/examples/elements.json, interview.json, scenes.json
- 확신도(confidence)는 LLM이 아니라 사용자가 입력하므로 여기에는 없습니다.
  요소와 확신도는 C의 DB(dream_element)에서 합쳐집니다.
"""
from pydantic import BaseModel, Field, field_validator

from app.core.enums import ElementType


class ExtractedElement(BaseModel):
    """꿈에서 뽑아낸 요소 하나 (인물/장소/물건/감정)."""

    type: ElementType
    name: str = Field(min_length=1, max_length=50, description="짧은 이름. 예: '할머니', '바닷가'")
    description: str = Field(default="", max_length=300, description="꿈 속에서 묘사된 모습. 없으면 빈 문자열")


class InterviewQuestion(BaseModel):
    """되묻기 질문 하나. 특정 답을 유도하지 않는 열린 질문이어야 합니다."""

    order: int = Field(ge=1, description="1부터 시작하는 질문 순서")
    target_element: str | None = Field(
        default=None, description="질문 대상 요소의 name. 꿈 전체에 대한 질문이면 null"
    )
    question: str = Field(min_length=1, max_length=200)


def _check_order(items: list, label: str) -> list:
    """order 값이 1, 2, 3, ... 순서대로 빠짐없이 매겨졌는지 확인."""
    orders = [item.order for item in items]
    if orders != list(range(1, len(items) + 1)):
        raise ValueError(f"{label} order는 1부터 차례대로여야 합니다: {orders}")
    return items


class ExtractionResult(BaseModel):
    """extract_and_ask(text)의 결과: 요소 추출 + 되묻기 질문 5~7개."""

    elements: list[ExtractedElement]
    questions: list[InterviewQuestion] = Field(min_length=5, max_length=7)

    @field_validator("questions")
    @classmethod
    def _questions_in_order(cls, v: list[InterviewQuestion]) -> list[InterviewQuestion]:
        return _check_order(v, "질문")


class ReextractionResult(BaseModel):
    """reextract(text, answers)의 결과: 인터뷰 답변을 반영한 요소 목록."""

    elements: list[ExtractedElement]


class Scene(BaseModel):
    """장면 하나. 요약은 화면 표시용(한국어), 프롬프트는 이미지 생성용(영어)."""

    order: int = Field(ge=1)
    summary_ko: str = Field(min_length=1, max_length=300, description="스토리보드에 보여 줄 한국어 요약")
    element_names: list[str] = Field(
        default_factory=list, description="이 장면에 나오는 요소 name. E1이 장면 확신도를 계산할 때 사용"
    )
    image_prompt_en: str = Field(min_length=1, max_length=1000, description="이미지 생성 API에 넣을 영어 프롬프트")


class SceneSplitResult(BaseModel):
    """split_scenes(...)의 결과: 장면 3~5개."""

    scenes: list[Scene] = Field(min_length=3, max_length=5)

    @field_validator("scenes")
    @classmethod
    def _scenes_in_order(cls, v: list[Scene]) -> list[Scene]:
        return _check_order(v, "장면")
