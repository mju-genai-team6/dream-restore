"""generate_narration 작업 함수 테스트. 실제 TTS API는 부르지 않고 가짜 클라이언트를 쓴다."""
import logging
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

try:  # openai SDK 버전에 따라 httpx 또는 httpx2를 쓴다
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from app.core.enums import FailureCode, JobStage, JobType
from app.jobs.context import JobError
from app.jobs.registry import HANDLERS
from app.storage import paths
from worker.render import narration


def _fake_mp3(frames: int = 100) -> bytes:
    """MPEG-1 Layer III, 128kbps, 44.1kHz 빈 프레임. 프레임당 1152샘플 → 100프레임 ≈ 2.61초."""
    header = bytes([0xFF, 0xFB, 0x90, 0x64])
    frame = header + bytes(417 - len(header))
    return frame * frames


class FakeCtx:
    job_id = 9
    dream_id = 1

    def __init__(self, root: Path):
        self.root = root
        self.stages: list[JobStage] = []
        self.logger = logging.getLogger("test")

    def report_stage(self, stage):
        self.stages.append(stage)

    def path_for(self, kind, **ids):
        return self.root / getattr(paths, kind)(self.dream_id, **ids)

    def tmp_dir(self):
        return self.root / paths.job_tmp(self.job_id)


class FakeClient:
    """outcomes 순서대로 예외를 던지거나 음성 바이트를 돌려준다."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.audio = SimpleNamespace(speech=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(content=outcome)


def _timeout():
    return openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/audio/speech"))


PAYLOAD = {"scene_id": 2, "version_no": 1, "text": "분홍색 카디건을 입은 할머니가 노란 우산을 건넨다."}
TARGET = "dreams/1/scenes/2/v1/narration.mp3"


@pytest.fixture
def ctx(tmp_path):
    return FakeCtx(tmp_path)


@pytest.fixture
def use_client(monkeypatch):
    monkeypatch.setattr(narration, "sleep", lambda _s: None)

    def _use(client):
        monkeypatch.setattr(narration, "get_client", lambda: client)
        return client

    return _use


def test_handler_registered():
    assert HANDLERS[JobType.GENERATE_NARRATION] is narration.handle_generate_narration


def test_success_saves_mp3_with_duration(ctx, use_client):
    client = use_client(FakeClient(_fake_mp3()))
    result = narration.handle_generate_narration(ctx, PAYLOAD)

    assert (ctx.root / TARGET).exists()
    assert result["narration_path"] == TARGET
    assert result["duration_seconds"] == pytest.approx(2.61, abs=0.05)
    assert result["attempts"] == 1
    assert client.calls[0]["response_format"] == "mp3"
    assert client.calls[0]["input"] == PAYLOAD["text"]
    assert ctx.stages == [JobStage.REQUESTING, JobStage.SAVING]


def test_timeout_retried_then_succeeds(ctx, use_client):
    use_client(FakeClient(_timeout(), _fake_mp3()))
    assert narration.handle_generate_narration(ctx, PAYLOAD)["attempts"] == 2


def test_timeout_gives_up(ctx, use_client):
    client = use_client(FakeClient(_timeout(), _timeout(), _timeout()))
    with pytest.raises(JobError) as e:
        narration.handle_generate_narration(ctx, PAYLOAD)
    assert e.value.code == FailureCode.TIMEOUT
    assert len(client.calls) == 3
    assert not (ctx.root / TARGET).exists()


def test_not_mp3_is_provider_error(ctx, use_client):
    use_client(FakeClient(b"not audio"))
    with pytest.raises(JobError) as e:
        narration.handle_generate_narration(ctx, PAYLOAD)
    assert e.value.code == FailureCode.PROVIDER_ERROR
    assert not (ctx.root / TARGET).exists()


def test_existing_narration_not_overwritten(ctx, use_client):
    target = ctx.root / TARGET
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    use_client(FakeClient(_fake_mp3()))
    with pytest.raises(JobError) as e:
        narration.handle_generate_narration(ctx, PAYLOAD)
    assert e.value.code == FailureCode.INVALID_INPUT
    assert target.read_bytes() == b"old"


@pytest.mark.parametrize(
    "payload",
    [
        {"version_no": 1, "text": "x"},
        {"scene_id": 2, "version_no": 0, "text": "x"},
        {"scene_id": 2, "version_no": 1, "text": "   "},
        {"scene_id": 2, "version_no": 1, "text": "가" * 201},
    ],
)
def test_invalid_payload(ctx, use_client, payload):
    use_client(FakeClient())
    with pytest.raises(JobError) as e:
        narration.handle_generate_narration(ctx, payload)
    assert e.value.code == FailureCode.INVALID_INPUT
