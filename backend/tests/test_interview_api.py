"""질문 조회·답변 저장 API (C-S2-02)."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core.enums import ExtractionPhase
from app.llm import client as llm_client
from app.main import app
from app.services.stubs import store
from tests.llm_fakes import FakeLlm

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}


@pytest.fixture(autouse=True)
def _clear_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture
def llm(monkeypatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client, "openai_complete", fake)
    return fake


def _text_dream() -> int:
    return client.post("/dreams", json=TEXT).json()["dream_id"]


def test_first_get_creates_questions_and_refresh_returns_same(llm):
    dream_id = _text_dream()

    first = client.get(f"/dreams/{dream_id}/interview")
    assert first.status_code == 200, first.text
    assert "X-Mock" not in first.headers
    body = first.json()
    assert body["total"] == 6
    assert body["answered"] == 0
    assert [q["order"] for q in body["questions"]] == [1, 2, 3, 4, 5, 6]
    assert body["questions"][1]["question"] == "할머니는 어떤 모습이었나요?"
    assert body["questions"][1]["target_element"] == "할머니"
    assert body["questions"][5]["target_element"] is None

    again = client.get(f"/dreams/{dream_id}/interview").json()
    assert again == body
    assert llm.kind_count("extract_and_ask") == 1

    detail = client.get(f"/dreams/{dream_id}").json()
    assert detail["status"] == "interviewing"
    assert detail["interview_progress"] == {"answered": 0, "total": 6}


def test_first_get_saves_raw_extraction_with_null_confidence(llm):
    dream_id = _text_dream()
    client.get(f"/dreams/{dream_id}/interview")

    [extraction] = store.extractions.values()
    assert extraction.phase == ExtractionPhase.RAW.value
    assert extraction.element_count == 5
    assert extraction.text_length == len(TEXT["text"])
    assert len(extraction.payload["questions"]) == 6
    elements = [e for e in store.elements.values() if e.extraction_id == extraction.id]
    assert len(elements) == 5
    assert all(e.confidence is None for e in elements)
    assert store.questions[1].text == "복도에서 기억나는 것을 자유롭게 말해 주세요."


def test_voice_dream_without_confirmed_text_is_rejected(llm):
    dream_id = client.post("/dreams", json={"input_type": "voice"}).json()["dream_id"]

    res = client.get(f"/dreams/{dream_id}/interview")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert llm.calls == []


def test_unknown_dream_returns_not_found(llm):
    assert client.get("/dreams/999/interview").status_code == 404
    res = client.post("/dreams/999/interview", json={"question_id": 1, "answer": "답"})
    assert res.status_code == 404


def test_answer_and_skip_update_progress(llm):
    dream_id = _text_dream()
    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]

    res = client.post(
        f"/dreams/{dream_id}/interview",
        json={"question_id": questions[0]["question_id"], "answer": "형광등이 깜빡였어요."},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"remaining": 5, "completed": False}

    res = client.post(
        f"/dreams/{dream_id}/interview",
        json={"question_id": questions[1]["question_id"], "answer": "무시됨", "skipped": True},
    )
    assert res.json() == {"remaining": 4, "completed": False}
    assert store.questions[questions[1]["question_id"]].answer is None

    body = client.get(f"/dreams/{dream_id}/interview").json()
    assert body["answered"] == 2
    assert [(q["answered"], q["skipped"]) for q in body["questions"][:3]] == [
        (True, False),
        (True, True),
        (False, False),
    ]
    assert client.get(f"/dreams/{dream_id}").json()["interview_progress"] == {"answered": 2, "total": 6}

    for q in questions[2:]:
        res = client.post(f"/dreams/{dream_id}/interview", json={"question_id": q["question_id"], "skipped": True})
    assert res.json() == {"remaining": 0, "completed": True}
    assert llm.kind_count("reextract") == 0


def test_answer_can_be_changed_before_reextract(llm):
    dream_id = _text_dream()
    question_id = client.get(f"/dreams/{dream_id}/interview").json()["questions"][0]["question_id"]

    client.post(f"/dreams/{dream_id}/interview", json={"question_id": question_id, "skipped": True})
    res = client.post(f"/dreams/{dream_id}/interview", json={"question_id": question_id, "answer": "기억났어요"})

    assert res.status_code == 200
    assert store.questions[question_id].answer == "기억났어요"
    assert store.questions[question_id].skipped is False


def test_answer_rejected_for_question_of_other_dream(llm):
    first = _text_dream()
    second = _text_dream()
    client.get(f"/dreams/{first}/interview")
    other_question = client.get(f"/dreams/{second}/interview").json()["questions"][0]["question_id"]

    res = client.post(f"/dreams/{first}/interview", json={"question_id": other_question, "answer": "답"})
    assert res.status_code == 404
    assert res.json()["error"]["detail"] == {"question_id": other_question}


def test_answer_rejected_before_questions_exist(llm):
    dream_id = _text_dream()

    res = client.post(f"/dreams/{dream_id}/interview", json={"question_id": 1, "answer": "답"})
    assert res.status_code == 409
    assert res.json()["error"]["detail"]["status"] == "recorded"


def test_llm_format_failure_returns_502_and_saves_nothing(monkeypatch):
    monkeypatch.setattr(llm_client, "openai_complete", FakeLlm(mode="bad_format"))
    dream_id = _text_dream()

    res = client.get(f"/dreams/{dream_id}/interview")
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "LLM_FAILED"
    assert store.questions == {}
    assert store.extractions == {}
    assert client.get(f"/dreams/{dream_id}").json()["status"] == "recorded"

    monkeypatch.setattr(llm_client, "openai_complete", FakeLlm())
    assert client.get(f"/dreams/{dream_id}/interview").status_code == 200


def test_llm_timeout_returns_504(monkeypatch):
    monkeypatch.setattr(llm_client, "openai_complete", FakeLlm(mode="timeout"))
    dream_id = _text_dream()

    res = client.get(f"/dreams/{dream_id}/interview")
    assert res.status_code == 504
    assert res.json()["error"]["code"] == "UPSTREAM_TIMEOUT"


def test_concurrent_first_get_calls_llm_once(monkeypatch):
    llm = FakeLlm(delay=0.3)
    monkeypatch.setattr(llm_client, "openai_complete", llm)
    dream_id = _text_dream()

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: client.get(f"/dreams/{dream_id}/interview"), range(5)))

    assert [r.status_code for r in responses] == [200] * 5
    assert llm.kind_count("extract_and_ask") == 1
    assert len({tuple(q["question_id"] for q in r.json()["questions"]) for r in responses}) == 1
    assert len(store.questions) == 6
    assert len(store.extractions) == 1
