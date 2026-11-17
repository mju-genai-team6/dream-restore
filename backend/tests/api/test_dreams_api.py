"""꿈 기록 생성·조회·원문 확정 API (C-S1-05)."""
from fastapi.testclient import TestClient

from app.core.enums import DreamStatus
from app.main import app
from app.repositories import dreams as dream_repo
from app.repositories import extractions as extraction_repo
from app.repositories import renders as render_repo
from app.repositories import scenes as scene_repo
from tests.repositories.helpers import ELEMENTS_PAYLOAD, SCENES

client = TestClient(app)

VOICE = {"input_type": "voice"}
TEXT = {"input_type": "text", "text": "학교 복도에서 할머니를 만났다."}
CONFIRM = {"confirmed_text": "확정한 원문"}


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


def test_text_dream_is_saved_to_db(read_db):
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]

    dream = dream_repo.get_dream(read_db, dream_id)
    assert dream.input_type == "text"
    assert dream.raw_text == dream.confirmed_text == TEXT["text"]
    assert dream.status == DreamStatus.RECORDED.value


def test_latest_render_and_is_latest(session_factory):
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    with session_factory.begin() as s:
        extraction_repo.save_extraction(s, dream_id, "after_interview", ELEMENTS_PAYLOAD, text_length=10)
        first_scene = scene_repo.create_scenes(s, dream_id, SCENES)[0]
        queued = render_repo.create_render(s, dream_id)
    assert client.get(f"/dreams/{dream_id}").json()["latest_render"] is None

    with session_factory.begin() as s:
        render_repo.complete_render(
            s, queued.id, video_path=f"dreams/{dream_id}/renders/{queued.id}/video.mp4", width=1280, height=720, duration=9
        )
    assert client.get(f"/dreams/{dream_id}").json()["latest_render"] == {
        "render_id": queued.id,
        "video_url": f"/storage/dreams/{dream_id}/renders/{queued.id}/video.mp4",
        "is_latest": True,
    }

    with session_factory.begin() as s:
        revised = scene_repo.add_scene_version(s, first_scene.id, summary_ko="수정", prompt_en="revised")
        scene_repo.set_current_version(s, first_scene.id, revised.id)
    assert client.get(f"/dreams/{dream_id}").json()["latest_render"]["is_latest"] is False


def test_confirm_rejected_when_status_is_not_recorded(session_factory):
    created = client.post("/dreams", json=VOICE)
    dream_id = created.json()["dream_id"]
    with session_factory.begin() as s:
        dream_repo.transition_status(s, dream_id, DreamStatus.RECORDED, DreamStatus.INTERVIEWING)

    res = client.patch(f"/dreams/{dream_id}", json=CONFIRM)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert res.json()["error"]["detail"]["status"] == "interviewing"
