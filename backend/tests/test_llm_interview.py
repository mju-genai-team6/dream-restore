"""인터뷰 모듈 테스트. 실제 API를 부르지 않고 가짜 LLM 응답으로 확인합니다."""
import json
from pathlib import Path

import pytest

from app.llm.client import (
    MAX_RETRIES,
    LlmCallError,
    LlmSchemaError,
    SttError,
    load_prompt,
)
from app.llm.interview import NO_MEMORY, extract_and_ask, reextract, transcribe
from app.llm.schemas import InterviewAnswer

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "examples"
GOOD_EXTRACTION = (EXAMPLES / "interview.json").read_text(encoding="utf-8")
GOOD_ELEMENTS = (EXAMPLES / "elements.json").read_text(encoding="utf-8")


class FakeLlm:
    """미리 정해 둔 답을 차례로 돌려주고, 받은 대화를 기록하는 가짜 LLM."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def __call__(self, messages):
        self.calls.append([dict(m) for m in messages])
        return self.replies[len(self.calls) - 1]


def test_prompts_exist():
    assert "5개 이상 7개 이하" in load_prompt("extract_and_ask")
    assert NO_MEMORY in load_prompt("reextract")


def test_extract_and_ask_returns_validated_result():
    llm = FakeLlm(GOOD_EXTRACTION)
    result = extract_and_ask("학교 복도에서 할머니가 우산을 줬다.", complete=llm)
    assert len(result.elements) == 5
    assert 5 <= len(result.questions) <= 7
    assert len(llm.calls) == 1
    assert "학교 복도에서 할머니가 우산을 줬다." in llm.calls[0][1]["content"]


def test_retries_on_bad_format_then_succeeds():
    llm = FakeLlm("JSON이 아닌 답", GOOD_EXTRACTION)
    result = extract_and_ask("꿈 내용", complete=llm)
    assert len(result.questions) == 6
    assert len(llm.calls) == 2
    # 두 번째 요청에는 무엇이 틀렸는지 알려 주는 메시지가 들어간다
    assert "형식과 맞지 않습니다" in llm.calls[1][-1]["content"]


def test_gives_up_after_max_retries():
    llm = FakeLlm(*["{}"] * (1 + MAX_RETRIES))
    with pytest.raises(LlmSchemaError):
        extract_and_ask("꿈 내용", complete=llm)
    assert len(llm.calls) == 1 + MAX_RETRIES


def test_question_target_must_be_extracted_element():
    data = json.loads(GOOD_EXTRACTION)
    data["questions"][0]["target_element"] = "원문에 없는 사람"
    llm = FakeLlm(json.dumps(data, ensure_ascii=False), GOOD_EXTRACTION)
    extract_and_ask("꿈 내용", complete=llm)
    assert len(llm.calls) == 2


def test_reextract_includes_answers_and_marks_no_memory():
    llm = FakeLlm(GOOD_ELEMENTS)
    answers = [
        InterviewAnswer(question="할머니는 어떤 모습이었나요?", answer="분홍색 카디건을 입고 있었어요"),
        InterviewAnswer(question="우산은 어떻게 생겼나요?", answer=""),
        InterviewAnswer(question="꿈이 어떻게 끝났나요?"),
    ]
    result = reextract("학교 복도에서 할머니가 우산을 줬다.", answers, complete=llm)
    assert len(result.elements) == 6
    sent = llm.calls[0][1]["content"]
    assert "분홍색 카디건" in sent
    assert sent.count(NO_MEMORY) == 2


def test_empty_text_rejected():
    with pytest.raises(ValueError):
        extract_and_ask("   ", complete=FakeLlm(GOOD_EXTRACTION))


def test_transcribe_missing_file():
    with pytest.raises(SttError):
        transcribe("/없는/파일.m4a")


def test_missing_api_key_gives_clear_error(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(LlmCallError):
        extract_and_ask("꿈 내용")
