"""요소 목록·확신도 저장 API (C-S2-03)."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.enums import ExtractionPhase
from app.llm import client as llm_client
from app.llm.interview import NO_MEMORY
from app.main import app
from app.repositories import extractions as extraction_repo
from tests.api import rows
from tests.llm_fakes import FakeLlm

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}


@pytest.fixture
def llm(monkeypatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client, "openai_complete", fake)
    return fake


def _interviewing_dream(answer_all: bool = True) -> int:
    """질문을 만들고 첫 질문에 답한다. answer_all이면 나머지는 건너뛰어 인터뷰를 끝낸다."""
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]
    client.post(
        f"/dreams/{dream_id}/interview",
        json={"question_id": questions[0]["question_id"], "answer": "분홍색 카디건을 입었어요"},
    )
    if answer_all:
        for q in questions[1:]:
            client.post(f"/dreams/{dream_id}/interview", json={"question_id": q["question_id"], "skipped": True})
    return dream_id


def _raw_element_ids(db: Session, dream_id: int) -> set[int]:
    return {e.id for e in extraction_repo.list_elements(db, dream_id, phase=ExtractionPhase.RAW)}


def test_elements_rejected_until_interview_is_done(llm):
    dream_id = _interviewing_dream(answer_all=False)

    res = client.get(f"/dreams/{dream_id}/elements")
    assert res.status_code == 409
    error = res.json()["error"]
    assert error["code"] == "INVALID_STATE"
    assert error["detail"] == {"status": "interviewing", "answered": 1, "total": 6}
    assert llm.kind_count("reextract") == 0


def test_elements_rejected_before_interview_starts(llm):
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]

    res = client.get(f"/dreams/{dream_id}/elements")
    assert res.status_code == 409
    assert res.json()["error"]["detail"]["total"] == 0


def test_first_get_reextracts_and_refresh_returns_saved(llm, read_db):
    dream_id = _interviewing_dream()

    first = client.get(f"/dreams/{dream_id}/elements")
    assert first.status_code == 200, first.text
    assert "X-Mock" not in first.headers
    elements = first.json()["elements"]
    assert len(elements) == 6
    assert elements[1] == {
        "element_id": elements[1]["element_id"],
        "type": "person",
        "name": "할머니",
        "description": "흰 머리에 분홍색 카디건을 입음",
        "confidence": None,
    }
    assert {e["element_id"] for e in elements}.isdisjoint(_raw_element_ids(read_db, dream_id))

    assert client.get(f"/dreams/{dream_id}/elements").json() == first.json()
    assert llm.kind_count("reextract") == 1
    assert [e.phase for e in rows.extractions(read_db)] == ["raw", "after_interview"]


def test_reextract_receives_answers_and_skips_as_no_memory(llm):
    dream_id = _interviewing_dream()
    client.get(f"/dreams/{dream_id}/elements")

    [(_, messages)] = [call for call in llm.calls if call[0] == "reextract"]
    sent = messages[1]["content"]
    assert TEXT["text"] in sent
    assert "분홍색 카디건을 입었어요" in sent
    assert sent.count(NO_MEMORY) == 5


def test_answer_rejected_after_reextract(llm):
    dream_id = _interviewing_dream()
    question_id = client.get(f"/dreams/{dream_id}/interview").json()["questions"][0]["question_id"]
    client.get(f"/dreams/{dream_id}/elements")

    res = client.post(f"/dreams/{dream_id}/interview", json={"question_id": question_id, "answer": "바꿈"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"


def test_partial_confidence_save_and_read_back(llm):
    dream_id = _interviewing_dream()
    elements = client.get(f"/dreams/{dream_id}/elements").json()["elements"]
    first, second = elements[0]["element_id"], elements[1]["element_id"]

    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": first, "confidence": "high"}, {"element_id": second, "confidence": "low"}]},
    )
    assert res.status_code == 200, res.text
    saved = {e["element_id"]: e["confidence"] for e in res.json()["elements"]}
    assert saved[first] == "high"
    assert saved[second] == "low"
    assert sum(1 for value in saved.values() if value is None) == 4

    read_back = {e["element_id"]: e["confidence"] for e in client.get(f"/dreams/{dream_id}/elements").json()["elements"]}
    assert read_back == saved

    res = client.put(
        f"/dreams/{dream_id}/elements/confidence", json={"items": [{"element_id": first, "confidence": "medium"}]}
    )
    assert {e["element_id"]: e["confidence"] for e in res.json()["elements"]}[first] == "medium"


def test_confidence_rejects_element_not_in_latest_list(llm, read_db):
    dream_id = _interviewing_dream()
    elements = client.get(f"/dreams/{dream_id}/elements").json()["elements"]
    old_id = min(_raw_element_ids(read_db, dream_id))

    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={
            "items": [
                {"element_id": elements[0]["element_id"], "confidence": "high"},
                {"element_id": old_id, "confidence": "high"},
                {"element_id": 999, "confidence": "low"},
            ]
        },
    )
    assert res.status_code == 400
    error = res.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["detail"] == {"element_ids": [old_id, 999]}
    assert extraction_repo.list_elements(read_db, dream_id)[0].confidence is None


def test_confidence_rejects_duplicated_element(llm):
    dream_id = _interviewing_dream()
    element_id = client.get(f"/dreams/{dream_id}/elements").json()["elements"][0]["element_id"]

    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": element_id, "confidence": "high"}, {"element_id": element_id, "confidence": "low"}]},
    )
    assert res.status_code == 400
    assert res.json()["error"]["detail"] == {"element_ids": [element_id]}


def test_confidence_rejected_before_reextract(llm, read_db):
    dream_id = _interviewing_dream()
    raw_id = min(_raw_element_ids(read_db, dream_id))

    res = client.put(
        f"/dreams/{dream_id}/elements/confidence", json={"items": [{"element_id": raw_id, "confidence": "high"}]}
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"


def test_confidence_invalid_value_returns_400(llm):
    dream_id = _interviewing_dream()
    element_id = client.get(f"/dreams/{dream_id}/elements").json()["elements"][0]["element_id"]

    for items in ([], [{"element_id": element_id, "confidence": "x"}], [{"element_id": element_id}]):
        res = client.put(f"/dreams/{dream_id}/elements/confidence", json={"items": items})
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_dream_returns_not_found(llm):
    assert client.get("/dreams/999/elements").status_code == 404
    res = client.put("/dreams/999/elements/confidence", json={"items": [{"element_id": 1, "confidence": "high"}]})
    assert res.status_code == 404


def test_reextract_timeout_returns_504_and_can_retry(llm, monkeypatch, read_db):
    dream_id = _interviewing_dream()
    monkeypatch.setattr(llm_client, "openai_complete", FakeLlm(mode="timeout"))

    res = client.get(f"/dreams/{dream_id}/elements")
    assert res.status_code == 504
    assert res.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert len(rows.extractions(read_db)) == 1

    monkeypatch.setattr(llm_client, "openai_complete", FakeLlm())
    assert len(client.get(f"/dreams/{dream_id}/elements").json()["elements"]) == 6


def test_reextract_format_failure_returns_502(llm, monkeypatch):
    dream_id = _interviewing_dream()
    monkeypatch.setattr(llm_client, "openai_complete", FakeLlm(mode="bad_format"))

    res = client.get(f"/dreams/{dream_id}/elements")
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "LLM_FAILED"


def test_concurrent_first_get_reextracts_once(llm, monkeypatch, read_db):
    dream_id = _interviewing_dream()
    slow = FakeLlm(delay=0.3)
    monkeypatch.setattr(llm_client, "openai_complete", slow)

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: client.get(f"/dreams/{dream_id}/elements"), range(5)))

    assert [r.status_code for r in responses] == [200] * 5
    assert slow.kind_count("reextract") == 1
    assert len({tuple(e["element_id"] for e in r.json()["elements"]) for r in responses}) == 1
    assert len(rows.extractions(read_db)) == 2
