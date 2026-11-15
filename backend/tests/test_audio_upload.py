"""음성 업로드 저장 API (C-S1-06)."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.enums import DreamStatus
from app.main import app
from app.services import dreams as dream_service
from app.services import mock_data
from app.services.stubs import dreams as dream_repo
from app.services.stubs import store

client = TestClient(app)

AUDIO_BYTES = b"\x1aE\xdf\xa3fake-webm"
MB = 1024 * 1024


@pytest.fixture(autouse=True)
def storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store.clear()
    monkeypatch.setattr(settings, "storage_path", tmp_path)
    yield tmp_path
    store.clear()


def _voice_dream() -> int:
    return client.post("/dreams", json={"input_type": "voice"}).json()["dream_id"]


def _upload(dream_id: int, filename: str = "dream.webm", content_type: str = "audio/webm", data: bytes = AUDIO_BYTES):
    return client.post(f"/dreams/{dream_id}/audio", files={"file": (filename, data, content_type)})


def _stored_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def test_upload_saves_file_under_audio_path(storage_root: Path):
    dream_id = _voice_dream()

    res = _upload(dream_id, content_type="audio/webm;codecs=opus")

    assert res.status_code == 201, res.text
    assert res.headers["X-Mock"] == "true"
    body = res.json()
    assert body["transcript"] == mock_data.RAW_TEXT
    audio = store.audio_files[body["audio_id"]]
    assert audio.dream_id == dream_id
    assert re.fullmatch(rf"dreams/{dream_id}/audio/[0-9a-f]{{32}}\.webm", audio.path)
    assert audio.mime_type == "audio/webm"
    assert audio.size == len(AUDIO_BYTES)
    assert audio.duration is None
    assert (storage_root / audio.path).read_bytes() == AUDIO_BYTES
    assert _stored_files(storage_root) == [storage_root / audio.path]


def test_audio_m4a_is_recorded_as_x_m4a():
    dream_id = _voice_dream()

    res = _upload(dream_id, filename="dream.m4a", content_type="audio/m4a")

    assert res.status_code == 201, res.text
    audio = store.audio_files[res.json()["audio_id"]]
    assert audio.mime_type == "audio/x-m4a"
    assert audio.path.endswith(".m4a")


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("dream.wav", "audio/wav"), ("dream.mp3", "audio/webm"), ("dream", "audio/webm")],
)
def test_unsupported_format_returns_415(storage_root: Path, filename: str, content_type: str):
    dream_id = _voice_dream()

    res = _upload(dream_id, filename=filename, content_type=content_type)

    assert res.status_code == 415
    assert res.json()["error"]["code"] == "UNSUPPORTED_AUDIO"
    assert store.audio_files == {}
    assert _stored_files(storage_root) == []


def test_large_content_length_is_rejected_before_handler(storage_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audio_max_mb", 1)
    dream_id = _voice_dream()

    def _must_not_run(*args, **kwargs):
        raise AssertionError("핸들러까지 오면 안 됩니다")

    monkeypatch.setattr(dream_service, "upload_audio", _must_not_run)

    res = _upload(dream_id, data=b"0" * int(2.5 * MB))

    assert res.status_code == 413
    assert res.json()["error"]["code"] == "AUDIO_TOO_LARGE"
    assert res.json()["error"]["detail"] == {"max_mb": 1}
    assert _stored_files(storage_root) == []


def test_large_file_without_content_length_is_stopped_while_copying(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "audio_max_mb", 1)
    dream_id = _voice_dream()
    calls = []
    original = dream_service.upload_audio

    def _spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(dream_service, "upload_audio", _spy)
    boundary = "audio-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="dream.webm"\r\n'
        "Content-Type: audio/webm\r\n\r\n"
    ).encode() + b"0" * int(1.5 * MB) + f"\r\n--{boundary}--\r\n".encode()

    # 반복자 본문은 Content-Length 없이 chunked로 전송된다
    res = client.post(
        f"/dreams/{dream_id}/audio",
        content=iter([body]),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert res.status_code == 413
    assert res.json()["error"]["code"] == "AUDIO_TOO_LARGE"
    assert calls == [1]
    assert store.audio_files == {}
    assert _stored_files(storage_root) == []


def test_text_dream_returns_409():
    dream_id = client.post("/dreams", json={"input_type": "text", "text": "꿈 내용"}).json()["dream_id"]

    res = _upload(dream_id)

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert res.json()["error"]["detail"] == {"input_type": "text"}


def test_dream_not_recorded_returns_409():
    dream_id = _voice_dream()
    dream_repo.transition_status(None, dream_id, DreamStatus.INTERVIEWING.value)

    res = _upload(dream_id)

    assert res.status_code == 409
    assert res.json()["error"]["detail"] == {"status": "interviewing"}


def test_unknown_dream_returns_404():
    res = _upload(999)

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_reupload_records_new_file(storage_root: Path):
    dream_id = _voice_dream()

    first = _upload(dream_id, data=b"first")
    second = _upload(dream_id, data=b"second")

    assert first.status_code == second.status_code == 201
    first_audio = store.audio_files[first.json()["audio_id"]]
    second_audio = store.audio_files[second.json()["audio_id"]]
    assert first_audio.id != second_audio.id
    assert first_audio.path != second_audio.path
    assert (storage_root / first_audio.path).read_bytes() == b"first"
    assert (storage_root / second_audio.path).read_bytes() == b"second"
