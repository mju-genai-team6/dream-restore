"""음성 업로드 STT 연결 (C-S2-01). transcribe는 가짜로 바꿔 끼운다."""
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.enums import DreamStatus
from app.db.session import get_db
from app.main import app
from app.services import dreams as dream_service
from app.services.llm_calls import STT_FAILED_MESSAGE, dream_lock
from app.services.stubs import dreams as dream_repo
from app.services.stubs import store
from tests.audio_fakes import TRANSCRIPT, WEBM_BYTES, FakeTranscribe

client = TestClient(app)


@pytest.fixture(autouse=True)
def storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store.clear()
    monkeypatch.setattr(settings, "storage_path", tmp_path)
    yield tmp_path
    store.clear()


def _use_stt(monkeypatch: pytest.MonkeyPatch, fake: FakeTranscribe) -> FakeTranscribe:
    monkeypatch.setattr(dream_service, "transcribe", fake)
    return fake


def _voice_dream() -> int:
    return client.post("/dreams", json={"input_type": "voice"}).json()["dream_id"]


def _upload(dream_id: int, data: bytes = WEBM_BYTES):
    return client.post(f"/dreams/{dream_id}/audio", files={"file": ("dream.webm", data, "audio/webm")})


def _stored_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def test_transcript_is_saved_as_raw_text(monkeypatch):
    _use_stt(monkeypatch, FakeTranscribe("  하늘을 나는 꿈  "))
    dream_id = _voice_dream()

    res = _upload(dream_id)

    assert res.status_code == 201, res.text
    assert "X-Mock" not in res.headers
    assert res.json()["transcript"] == "하늘을 나는 꿈"
    fetched = client.get(f"/dreams/{dream_id}").json()
    assert fetched["raw_text"] == "하늘을 나는 꿈"
    assert fetched["confirmed_text"] is None
    assert fetched["status"] == DreamStatus.RECORDED.value


def test_reupload_after_confirm_clears_confirmed_text(monkeypatch):
    stt = _use_stt(monkeypatch, FakeTranscribe("첫 번째 녹음"))
    dream_id = _voice_dream()
    assert _upload(dream_id).status_code == 201
    assert client.patch(f"/dreams/{dream_id}", json={"confirmed_text": "확정한 원문"}).status_code == 200

    stt.text = "두 번째 녹음"
    res = _upload(dream_id)

    assert res.status_code == 201, res.text
    fetched = client.get(f"/dreams/{dream_id}").json()
    assert fetched["raw_text"] == "두 번째 녹음"
    assert fetched["confirmed_text"] is None
    assert fetched["status"] == DreamStatus.RECORDED.value


@pytest.mark.parametrize(
    ("mode", "status_code", "code"),
    [
        ("stt_error", 502, "STT_FAILED"),
        ("no_key", 502, "STT_FAILED"),
        ("timeout", 504, "UPSTREAM_TIMEOUT"),
    ],
)
def test_stt_failure_maps_to_api_error(monkeypatch, mode: str, status_code: int, code: str):
    _use_stt(monkeypatch, FakeTranscribe(mode=mode))
    dream_id = _voice_dream()

    res = _upload(dream_id)

    assert res.status_code == status_code, res.text
    assert res.json()["error"]["code"] == code
    if code == "STT_FAILED":
        assert res.json()["error"]["message"] == STT_FAILED_MESSAGE


@pytest.mark.parametrize("text", ["", "   \n\t"])
def test_empty_transcript_returns_502(monkeypatch, text: str):
    _use_stt(monkeypatch, FakeTranscribe(text))
    dream_id = _voice_dream()

    res = _upload(dream_id)

    assert res.status_code == 502
    assert res.json()["error"] == {"code": "STT_FAILED", "message": STT_FAILED_MESSAGE, "detail": {}}
    assert store.dreams[dream_id].raw_text is None


@pytest.mark.parametrize("mode", ["stt_error", "timeout"])
def test_failed_stt_keeps_audio_and_raw_text_but_clears_confirmed(
    storage_root: Path, monkeypatch, mode: str
):
    stt = _use_stt(monkeypatch, FakeTranscribe("이전 녹음"))
    dream_id = _voice_dream()
    assert _upload(dream_id).status_code == 201
    assert client.patch(f"/dreams/{dream_id}", json={"confirmed_text": "확정한 원문"}).status_code == 200

    stt.mode = mode
    res = _upload(dream_id, data=WEBM_BYTES + b"retry")

    assert res.status_code in (502, 504)
    dream = store.dreams[dream_id]
    assert dream.raw_text == "이전 녹음"
    assert dream.confirmed_text is None
    assert dream.status == DreamStatus.RECORDED.value
    assert len(store.audio_files) == 2
    for audio in store.audio_files.values():
        assert (storage_root / audio.path).is_file()
    assert len(_stored_files(storage_root)) == 2


def test_retry_after_failure_uses_same_endpoint(monkeypatch):
    stt = _use_stt(monkeypatch, FakeTranscribe("다시 녹음", mode="stt_error"))
    dream_id = _voice_dream()
    assert _upload(dream_id).status_code == 502

    stt.mode = "ok"
    res = _upload(dream_id)

    assert res.status_code == 201, res.text
    assert len(store.audio_files) == 2
    assert store.dreams[dream_id].raw_text == "다시 녹음"


class _RecordingSession:
    """실제 DB 세션 자리에 끼워 commit·rollback 순서를 기록한다."""

    def __init__(self, events: list[str]):
        self.events = events

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("ok", ["commit", "transcribe", "commit"]),
        ("stt_error", ["commit", "transcribe"]),
        ("timeout", ["commit", "transcribe"]),
    ],
)
def test_audio_record_is_committed_before_stt(monkeypatch, mode: str, expected: list[str]):
    events: list[str] = []
    dream_id = _voice_dream()
    dream_repo.update_confirmed_text(None, dream_id, "확정한 원문")

    def _check_committed(_path) -> None:
        # STT가 돌 때는 음성 기록과 확정 원문 비우기가 이미 commit되어 있어야 한다
        assert events == ["commit"]
        assert len(store.audio_files) == 1
        assert store.dreams[dream_id].confirmed_text is None
        events.append("transcribe")

    _use_stt(monkeypatch, FakeTranscribe(mode=mode, on_call=_check_committed))

    def _session():
        yield _RecordingSession(events)

    app.dependency_overrides[get_db] = _session

    res = _upload(dream_id)

    assert res.status_code in (201, 502, 504), res.text
    assert events == expected


def test_same_dream_stt_runs_one_at_a_time(monkeypatch):
    stt = _use_stt(monkeypatch, FakeTranscribe(delay=0.2))
    dream_id = _voice_dream()

    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: _upload(dream_id), range(3)))

    assert [r.status_code for r in responses] == [201] * 3
    assert len(stt.paths) == 3
    assert stt.max_running == 1
    assert store.dreams[dream_id].raw_text == TRANSCRIPT


def test_interview_started_while_waiting_for_lock_returns_409(storage_root: Path, monkeypatch):
    stt = _use_stt(monkeypatch, FakeTranscribe())
    dream_id = _voice_dream()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with dream_lock(dream_id):
            future = pool.submit(_upload, dream_id)
            time.sleep(0.3)
            dream_repo.transition_status(None, dream_id, DreamStatus.INTERVIEWING.value)
        res = future.result()

    assert res.status_code == 409
    assert res.json()["error"]["detail"] == {"status": "interviewing"}
    assert store.audio_files == {}
    assert _stored_files(storage_root) == []
    assert stt.paths == []
