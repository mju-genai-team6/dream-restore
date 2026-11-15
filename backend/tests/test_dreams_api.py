"""꿈 기록 생성·조회·원문 확정 API (C-S1-05)."""
import pytest
from fastapi.testclient import TestClient

from app.core.enums import DreamStatus
from app.main import app
from app.services.stubs import dreams as dream_repo
from app.services.stubs import store

client = TestClient(app)

VOICE = {"input_type": "voice"}
TEXT = {"input_type": "text", "text": "학교 복도에서 할머니를 만났다."}
CONFIRM = {"confirmed_text": "확정한 원문"}


@pytest.fixture(autouse=True)
def _clear_dream_store():
    store.clear()
    yield
    store.clear()


def test_voice_dream_create_get_and_confirm():
    created = client.post("/dreams", json=VOICE)
    assert created.status_code == 201, created.text
    assert "X-Mock" not in created.headers
    dream_id = created.json()["dream_id"]
    assert created.json()["status"] == "recorded"

    fetched = client.get(f"/dreams/{dream_id}")
    assert fetched.status_code == 200
    assert "X-Mock" not in fetched.headers
    detail = fetched.json()
    assert detail["input_type"] == "voice"
    assert detail["status"] == "recorded"
    assert detail["raw_text"] is None
    assert detail["confirmed_text"] is None
    assert detail["interview_progress"] == {"answered": 0, "total": 0}
    assert detail["active_job"] is None
    assert detail["latest_render"] is None
    assert detail["created_at"]

    confirmed = client.patch(f"/dreams/{dream_id}", json=CONFIRM)
    assert confirmed.status_code == 200
    assert "X-Mock" not in confirmed.headers
    assert confirmed.json() == {"dream_id": dream_id, "status": "recorded"}

    again = client.get(f"/dreams/{dream_id}").json()
    assert again["confirmed_text"] == CONFIRM["confirmed_text"]
    assert again["raw_text"] is None
    assert again["status"] == "recorded"

    overwritten = client.patch(f"/dreams/{dream_id}", json={"confirmed_text": "다시 확정한 원문"})
    assert overwritten.status_code == 200
    assert client.get(f"/dreams/{dream_id}").json()["confirmed_text"] == "다시 확정한 원문"


def test_text_dream_is_confirmed_on_create():
    created = client.post("/dreams", json=TEXT)
    assert created.status_code == 201, created.text
    assert "X-Mock" not in created.headers
    dream_id = created.json()["dream_id"]
    assert created.json()["status"] == "recorded"

    detail = client.get(f"/dreams/{dream_id}").json()
    assert detail["input_type"] == "text"
    assert detail["raw_text"] == TEXT["text"]
    assert detail["confirmed_text"] == TEXT["text"]
    assert detail["status"] == "recorded"


def test_unknown_dream_returns_not_found():
    missing = client.get("/dreams/999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"

    confirmed = client.patch("/dreams/999", json=CONFIRM)
    assert confirmed.status_code == 404
    assert confirmed.json()["error"]["code"] == "NOT_FOUND"


def test_confirm_rejected_when_status_is_not_recorded():
    created = client.post("/dreams", json=VOICE)
    dream_id = created.json()["dream_id"]
    dream_repo.transition_status(None, dream_id, DreamStatus.INTERVIEWING.value)

    res = client.patch(f"/dreams/{dream_id}", json=CONFIRM)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert res.json()["error"]["detail"]["status"] == "interviewing"
