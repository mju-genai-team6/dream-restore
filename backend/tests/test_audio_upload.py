"""음성 업로드 저장 API (C-S1-06, 형식 판별은 C-S2-01)."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.enums import DreamStatus
from app.main import app
from app.services import dreams as dream_service
from app.services.stubs import dreams as dream_repo
from app.services.stubs import store
from tests.audio_fakes import MP4_BYTES, TRANSCRIPT, WEBM_BYTES, FakeTranscribe

client = TestClient(app)

AUDIO_BYTES = WEBM_BYTES
MB = 1024 * 1024


@pytest.fixture(autouse=True)
def storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store.clear()
    monkeypatch.setattr(settings, "storage_path", tmp_path)
    yield tmp_path
    store.clear()


@pytest.fixture(autouse=True)
def stt(monkeypatch: pytest.MonkeyPatch) -> FakeTranscribe:
    fake = FakeTranscribe()
    monkeypatch.setattr(dream_service, "transcribe", fake)
    return fake


def _voice_dream() -> int:
    return client.post("/dreams", json={"input_type": "voice"}).json()["dream_id"]


def _upload(dream_id: int, filename: str = "dream.webm", content_type: str = "audio/webm", data: bytes = AUDIO_BYTES):
    return client.post(f"/dreams/{dream_id}/audio", files={"file": (filename, data, content_type)})


def _stored_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def test_upload_saves_file_under_audio_path(storage_root: Path, stt: FakeTranscribe):
    dream_id = _voice_dream()

    res = _upload(dream_id, content_type="audio/webm;codecs=opus")

    assert res.status_code == 201, res.text
    assert "X-Mock" not in res.headers
    body = res.json()
    assert body["transcript"] == TRANSCRIPT
    audio = store.audio_files[body["audio_id"]]
    assert audio.dream_id == dream_id
    assert re.fullmatch(rf"dreams/{dream_id}/audio/[0-9a-f]{{32}}\.webm", audio.path)
    assert audio.mime_type == "audio/webm"
    assert audio.size == len(AUDIO_BYTES)
    assert audio.duration is None
    assert (storage_root / audio.path).read_bytes() == AUDIO_BYTES
    assert _stored_files(storage_root) == [storage_root / audio.path]


def test_transcribe_gets_absolute_path_of_saved_file(storage_root: Path, stt: FakeTranscribe):
    dream_id = _voice_dream()

    res = _upload(dream_id, filename="dream.webm", content_type="audio/webm", data=MP4_BYTES)

    assert res.status_code == 201, res.text
    audio = store.audio_files[res.json()["audio_id"]]
    [called] = stt.paths
    path = Path(called)
    assert path.is_absolute()
    assert path == (storage_root / audio.path).resolve()
    assert path.suffix == ".mp4"


def test_mp4_content_named_webm_is_saved_as_mp4(storage_root: Path):
    dream_id = _voice_dream()

    res = _upload(dream_id, filename="dream.webm", content_type="audio/webm", data=MP4_BYTES)

    assert res.status_code == 201, res.text
    audio = store.audio_files[res.json()["audio_id"]]
    assert audio.mime_type == "audio/mp4"
    assert audio.path.endswith(".mp4")
    assert (storage_root / audio.path).read_bytes() == MP4_BYTES


@pytest.mark.parametrize("content_type", ["audio/m4a", "audio/x-m4a"])
def test_mp4_content_with_m4a_type_is_recorded_as_x_m4a(content_type: str):
    dream_id = _voice_dream()

    res = _upload(dream_id, filename="dream.webm", content_type=content_type, data=MP4_BYTES)

    assert res.status_code == 201, res.text
    audio = store.audio_files[res.json()["audio_id"]]
    assert audio.mime_type == "audio/x-m4a"
    assert audio.path.endswith(".m4a")


def test_webm_content_with_mp4_type_is_saved_as_webm():
    dream_id = _voice_dream()

    res = _upload(dream_id, filename="dream.m4a", content_type="audio/mp4", data=WEBM_BYTES)

    assert res.status_code == 201, res.text
    audio = store.audio_files[res.json()["audio_id"]]
    assert audio.mime_type == "audio/webm"
    assert audio.path.endswith(".webm")


@pytest.mark.parametrize("filename", ["dream.mp3", "dream"])
def test_client_filename_extension_is_ignored(filename: str):
    dream_id = _voice_dream()

    res = _upload(dream_id, filename=filename, data=WEBM_BYTES)

    assert res.status_code == 201, res.text
    assert store.audio_files[res.json()["audio_id"]].path.endswith(".webm")


@pytest.mark.parametrize(
    ("content_type", "data"),
    [
        ("audio/wav", WEBM_BYTES),
        ("audio/ogg", MP4_BYTES),
        ("audio/webm", b"RIFF\x24\x00\x00\x00WAVEfmt "),
        ("audio/mp4", b"\x1a\x45\xdf"),
        ("audio/webm", b""),
    ],
)
def test_unsupported_format_returns_415(
    storage_root: Path, stt: FakeTranscribe, content_type: str, data: bytes
):
    dream_id = _voice_dream()

    res = _upload(dream_id, content_type=content_type, data=data)

    assert res.status_code == 415
    assert res.json()["error"]["code"] == "UNSUPPORTED_AUDIO"
    assert store.audio_files == {}
    assert _stored_files(storage_root) == []
    assert stt.paths == []


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
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="dream.webm"\r\n'
            "Content-Type: audio/webm\r\n\r\n"
        ).encode()
        + WEBM_BYTES
        + b"0" * int(1.5 * MB)
        + f"\r\n--{boundary}--\r\n".encode()
    )

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

    first = _upload(dream_id, data=WEBM_BYTES + b"first")
    second = _upload(dream_id, data=WEBM_BYTES + b"second")

    assert first.status_code == second.status_code == 201
    first_audio = store.audio_files[first.json()["audio_id"]]
    second_audio = store.audio_files[second.json()["audio_id"]]
    assert first_audio.id != second_audio.id
    assert first_audio.path != second_audio.path
    assert (storage_root / first_audio.path).read_bytes() == WEBM_BYTES + b"first"
    assert (storage_root / second_audio.path).read_bytes() == WEBM_BYTES + b"second"
