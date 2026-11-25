"""인터뷰 모듈 테스트. 실제 API를 부르지 않고 가짜 LLM 응답으로 확인합니다."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm import interview
from app.llm.client import (
    MAX_RETRIES,
    LlmCallError,
    LlmSchemaError,
    SttEmptyResultError,
    SttError,
    load_prompt,
)
from app.llm.interview import (
    NO_MEMORY,
    extract_and_ask,
    is_hallucination,
    reextract,
    transcribe,
)
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


# --- STT 무음·환각 거르기 (실제 Whisper 응답 모양을 흉내 낸 가짜) ---
def _seg(text: str, no_speech_prob: float) -> SimpleNamespace:
    return SimpleNamespace(text=f" {text}", no_speech_prob=no_speech_prob, avg_logprob=-0.3)


def _fake_whisper(monkeypatch, tmp_path, segments, text=None):
    """transcribe가 부르는 OpenAI 클라이언트를 가짜로 바꾸고, 보낸 인자를 기록한다."""
    sent: dict = {}

    def create(**kwargs):
        sent.update(kwargs)
        joined = text if text is not None else "".join(s.text for s in segments or []).strip()
        return SimpleNamespace(text=joined, segments=segments)

    fake = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    monkeypatch.setattr(interview, "get_openai_client", lambda: fake)
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    return audio, sent


@pytest.mark.parametrize(
    "segments",
    [
        [_seg("고맙습니다.", 0.94)],  # 실제 무음 6초 결과
        [_seg("시청해주셔서 감사합니다.", 0.88)],  # 실제 작은 잡음 6초 결과
        [_seg("MBC 뉴스 이덕영입니다.", 0.1)],  # no_speech_prob가 낮아도 알려진 문장이면 버림
        [],
    ],
)
def test_silent_or_hallucinated_audio_is_empty_result(monkeypatch, tmp_path, segments):
    audio, sent = _fake_whisper(monkeypatch, tmp_path, segments)
    with pytest.raises(SttEmptyResultError):
        transcribe(audio)
    assert sent["response_format"] == "verbose_json"
    assert sent["language"] == "ko"


def test_real_speech_kept_and_trailing_hallucination_dropped(monkeypatch, tmp_path):
    segments = [
        _seg("어젯밤 꿈에서 할머니랑 바닷가를 걸었어.", 0.0),
        _seg("갑자기 비가 와서 좀 무서웠어.", 0.01),
        _seg("시청해주셔서 감사합니다.", 0.7),
    ]
    audio, _ = _fake_whisper(monkeypatch, tmp_path, segments)
    assert transcribe(audio) == "어젯밤 꿈에서 할머니랑 바닷가를 걸었어. 갑자기 비가 와서 좀 무서웠어."


def test_without_segments_uses_whole_text(monkeypatch, tmp_path):
    audio, _ = _fake_whisper(monkeypatch, tmp_path, None, text="MBC 뉴스 이덕영입니다.")
    with pytest.raises(SttEmptyResultError):
        transcribe(audio)
    audio, _ = _fake_whisper(monkeypatch, tmp_path, None, text="학교 복도에 있었어.")
    assert transcribe(audio) == "학교 복도에 있었어."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("MBC 뉴스 이덕영입니다.", True),
        ("MBC 뉴스 김철수 기자입니다", True),
        ("시청해 주셔서 감사합니다!", True),
        ("구독과 좋아요 부탁드립니다", True),
        ("자막 제공 및 자막 편집", True),
        # 실제 꿈 내용 안에 섞인 말은 지우지 않는다 (문장 전체가 일치할 때만)
        ("꿈에서 MBC 뉴스를 보고 있었는데 아나운서가 할머니였어", False),
        ("할머니께 고맙다고 말했어", False),
    ],
)
def test_is_hallucination(text, expected):
    assert is_hallucination(text) is expected
