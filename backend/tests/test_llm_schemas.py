"""LLM 출력 스키마 테스트.

docs/schemas/examples/의 예시 JSON이 스키마와 항상 맞는지도 확인합니다.
(스키마를 바꿨는데 예시를 안 바꾸면 이 테스트가 실패합니다.)
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.llm.schemas import ExtractionResult, ReextractionResult, SceneSplitResult

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "examples"


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("interview.json", ExtractionResult),
        ("elements.json", ReextractionResult),
        ("scenes.json", SceneSplitResult),
    ],
)
def test_examples_match_schema(filename, model):
    data = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    model.model_validate(data)


def _questions(n: int) -> list[dict]:
    return [{"order": i, "question": f"질문 {i}"} for i in range(1, n + 1)]


def test_question_count_must_be_5_to_7():
    ExtractionResult.model_validate({"elements": [], "questions": _questions(5)})
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"elements": [], "questions": _questions(4)})
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"elements": [], "questions": _questions(8)})


def test_question_order_must_be_sequential():
    qs = _questions(5)
    qs[2]["order"] = 7
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"elements": [], "questions": qs})


def test_unknown_element_type_rejected():
    with pytest.raises(ValidationError):
        ReextractionResult.model_validate({"elements": [{"type": "animal", "name": "고양이"}]})


def test_scene_count_must_be_3_to_5():
    scene = {"summary_ko": "요약", "image_prompt_en": "prompt"}
    with pytest.raises(ValidationError):
        SceneSplitResult.model_validate({"scenes": [{**scene, "order": i} for i in (1, 2)]})
