"""LLM 출력 스키마 (D 담당).

LLM이 돌려준 JSON이 이 모양과 맞는지 Pydantic으로 검사합니다.
맞지 않으면 최대 2회 다시 요청하고, 그래도 실패하면 예외를 던집니다 (app/llm/README.md).

- 예시 JSON: docs/schemas/examples/elements.json, interview.json, scenes.json
- 확신도(confidence)는 LLM이 아니라 사용자가 입력하므로 여기에는 없습니다.
  요소와 확신도는 C의 DB(dream_element)에서 합쳐집니다.
"""
from pydantic import BaseModel, Field, field_validator, model_validator

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
        default=None,
        max_length=50,  # DB 컬럼 interview_questions.target_element가 varchar(50)
        description="질문 대상 요소의 name. 꿈 전체에 대한 질문이면 null",
    )
    question: str = Field(min_length=1, max_length=200)


def _check_order(items: list, label: str) -> list:
    """order 값이 1, 2, 3, ... 순서대로 빠짐없이 매겨졌는지 확인."""
    orders = [item.order for item in items]
    if orders != list(range(1, len(items) + 1)):
        raise ValueError(f"{label} order는 1부터 차례대로여야 합니다: {orders}")
    return items


def _check_unique_names(elements: list[ExtractedElement]) -> list[ExtractedElement]:
    """요소 name이 서로 겹치지 않는지 확인. 장면·질문이 요소를 name으로 가리키므로 겹치면 안 된다."""
    names = [e.name for e in elements]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise ValueError(f"요소 name이 겹칩니다. 서로 다른 이름을 붙여 주세요: {duplicated}")
    return elements


class ExtractionResult(BaseModel):
    """extract_and_ask(text)의 결과: 요소 추출 + 되묻기 질문 5~7개."""

    elements: list[ExtractedElement]
    questions: list[InterviewQuestion] = Field(min_length=5, max_length=7)

    @field_validator("elements")
    @classmethod
    def _unique_names(cls, v: list[ExtractedElement]) -> list[ExtractedElement]:
        return _check_unique_names(v)

    @field_validator("questions")
    @classmethod
    def _questions_in_order(cls, v: list[InterviewQuestion]) -> list[InterviewQuestion]:
        return _check_order(v, "질문")

    @model_validator(mode="after")
    def _targets_exist(self) -> "ExtractionResult":
        """질문 대상(target_element)은 추출된 요소 이름 중 하나여야 합니다."""
        names = {e.name for e in self.elements}
        unknown = [q.target_element for q in self.questions if q.target_element and q.target_element not in names]
        if unknown:
            raise ValueError(f"target_element가 elements의 name에 없습니다: {unknown}")
        return self


class InterviewAnswer(BaseModel):
    """reextract에 넘기는 질문-답변 한 쌍. 답이 비어 있으면 '기억나지 않음'으로 처리합니다."""

    question: str
    answer: str | None = None


class ReextractionResult(BaseModel):
    """reextract(text, answers)의 결과: 인터뷰 답변을 반영한 요소 목록."""

    elements: list[ExtractedElement]

    @field_validator("elements")
    @classmethod
    def _unique_names(cls, v: list[ExtractedElement]) -> list[ExtractedElement]:
        return _check_unique_names(v)


class Scene(BaseModel):
    """장면 하나. 요약은 화면 표시용(한국어), 프롬프트는 이미지 생성용(영어)."""

    order: int = Field(ge=1)
    summary_ko: str = Field(min_length=1, max_length=300, description="스토리보드에 보여 줄 한국어 요약")
    element_names: list[str] = Field(
        default_factory=list, description="이 장면에 나오는 요소 name. E1이 장면 확신도를 계산할 때 사용"
    )
    image_prompt_en: str = Field(
        min_length=1,
        max_length=1000,
        description="장면 내용만 담은 영어 프롬프트. 화풍과 인물 외형은 E2가 뒤에 붙이므로 넣지 않음",
    )


class SceneCharacter(BaseModel):
    """꿈에 나온 인물의 영어 외형 묘사. 모든 장면에 같은 문구를 써서 인물 모습을 유지합니다 (E2).

    E2 payload의 characters 항목 {"name", "appearance"}에 name_en, appearance_en을 넣으면 됩니다.
    """

    name: str = Field(min_length=1, description="인물 요소의 name (한국어, dream_elements.name과 같음)")
    name_en: str = Field(min_length=1, max_length=50, description="image_prompt_en에서 이 인물을 부르는 영어 이름")
    appearance_en: str = Field(
        default="", max_length=300, description="사용자가 말한 외형만 영어로. 말한 것이 없으면 빈 문자열"
    )


class SceneSplitResult(BaseModel):
    """split_scenes(...)의 결과: 장면 3~5개와 인물 외형 목록."""

    scenes: list[Scene] = Field(min_length=3, max_length=5)
    characters: list[SceneCharacter] = Field(default_factory=list)

    @field_validator("scenes")
    @classmethod
    def _scenes_in_order(cls, v: list[Scene]) -> list[Scene]:
        return _check_order(v, "장면")
