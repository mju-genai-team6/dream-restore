"""장면 모듈 테스트. 실제 API를 부르지 않고 가짜 LLM 응답으로 확인합니다."""
import json
from pathlib import Path

import httpx
import openai
import pytest

from app.llm import client
from app.llm.client import MAX_RETRIES, LlmSchemaError, LlmTimeoutError, load_prompt
from app.llm.scenes import split_scenes
from app.llm.schemas import InterviewAnswer, ReextractionResult

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "examples"
GOOD_SCENES = (EXAMPLES / "scenes.json").read_text(encoding="utf-8")
ELEMENTS = ReextractionResult.model_validate_json(
    (EXAMPLES / "elements.json").read_text(encoding="utf-8")
).elements
TEXT = "학교 복도에서 할머니가 우산을 줬다. 창밖은 바다였다."
ANSWERS = [
    InterviewAnswer(question="할머니는 어떤 모습이었나요?", answer="분홍색 카디건을 입고 있었어요"),
    InterviewAnswer(question="꿈이 어떻게 끝났나요?", answer=None),
]


class FakeLlm:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def __call__(self, messages):
        self.calls.append([dict(m) for m in messages])
        return self.replies[len(self.calls) - 1]


def _changed(change) -> str:
    data = json.loads(GOOD_SCENES)
    change(data)
    return json.dumps(data, ensure_ascii=False)


def test_split_scenes_returns_validated_result():
    llm = FakeLlm(GOOD_SCENES)
    result = split_scenes(TEXT, ANSWERS, ELEMENTS, complete=llm)
    assert [s.order for s in result.scenes] == [1, 2, 3]
    assert result.characters[0].name == "할머니"
    assert len(llm.calls) == 1
    sent = llm.calls[0][1]["content"]
    assert TEXT in sent and "분홍색 카디건" in sent and "(기억나지 않음)" in sent
    assert "type: person | name: 할머니" in sent


def test_result_fits_create_scenes_input():
    """repositories.scenes.create_scenes가 읽는 키가 그대로 있어야 한다."""
    result = split_scenes(TEXT, ANSWERS, ELEMENTS, complete=FakeLlm(GOOD_SCENES))
    for scene in result.model_dump()["scenes"]:
        assert {"order", "summary_ko", "element_names", "image_prompt_en"} <= scene.keys()


def test_unknown_element_name_is_retried():
    bad = _changed(lambda d: d["scenes"][0]["element_names"].append("없는 요소"))
    llm = FakeLlm(bad, GOOD_SCENES)
    split_scenes(TEXT, ANSWERS, ELEMENTS, complete=llm)
    assert len(llm.calls) == 2
    assert "없는 요소" in llm.calls[1][-1]["content"]


def test_scene_without_elements_is_retried():
    bad = _changed(lambda d: d["scenes"][2].update(element_names=[]))
    llm = FakeLlm(bad, GOOD_SCENES)
    split_scenes(TEXT, ANSWERS, ELEMENTS, complete=llm)
    assert len(llm.calls) == 2


def test_missing_character_is_retried():
    bad = _changed(lambda d: d.update(characters=[]))
    llm = FakeLlm(bad, GOOD_SCENES)
    split_scenes(TEXT, ANSWERS, ELEMENTS, complete=llm)
    assert len(llm.calls) == 2


def test_gives_up_after_max_retries():
    bad = _changed(lambda d: d.update(scenes=d["scenes"][:2]))  # 장면 2개 (3개 미만)
    llm = FakeLlm(*[bad] * (1 + MAX_RETRIES))
    with pytest.raises(LlmSchemaError):
        split_scenes(TEXT, ANSWERS, ELEMENTS, complete=llm)
    assert len(llm.calls) == 1 + MAX_RETRIES


def test_empty_inputs_rejected():
    with pytest.raises(ValueError):
        split_scenes("  ", ANSWERS, ELEMENTS, complete=FakeLlm(GOOD_SCENES))
    with pytest.raises(ValueError):
        split_scenes(TEXT, ANSWERS, [], complete=FakeLlm(GOOD_SCENES))


def test_prompt_forbids_style_words():
    prompt = load_prompt("split_scenes")
    assert "화풍" in prompt and "3개 이상 5개 이하" in prompt


def test_timeout_raises_llm_timeout_error(monkeypatch):
    """시간 초과는 LlmTimeoutError로 구분되고, 기존 코드가 보던 __cause__도 그대로 남는다."""

    class Completions:
        def create(self, **kwargs):
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

    class FakeClient:
        class chat:
            completions = Completions()

    monkeypatch.setattr(client, "get_openai_client", lambda: FakeClient())
    with pytest.raises(LlmTimeoutError) as info:
        client.openai_complete([{"role": "user", "content": "hi"}])
    assert isinstance(info.value, client.LlmCallError)
    assert isinstance(info.value.__cause__, openai.APITimeoutError)
