"""콘텐츠 정책 거부 시 표현 완화 규칙 (E2 계획서 3.2). 실제 이미지 API는 부르지 않는다.

규칙: 거부되면 순화 문구(SOFTEN_PREFIX)를 붙여 한 번만 더 시도하고, 또 거부되면 CONTENT_POLICY로 실패한다.
"""
import base64
import logging
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest
from PIL import Image

try:  # openai SDK 버전에 따라 httpx 또는 httpx2를 쓴다
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from app.core.enums import FailureCode
from app.jobs.context import JobError
from app.storage import paths
from worker.image_gen import generate
from worker.image_gen.config import image_settings as img_cfg
from worker.image_gen.prompt import SOFTEN_PREFIX, soften_prompt

PAYLOAD = {"scene_id": 5, "version_no": 1, "image_prompt_en": "A monster chasing me down a dark hallway"}


def _png_b64() -> str:
    buf = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _rejected():
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    response = httpx.Response(400, request=request)
    return openai.BadRequestError("rejected", response=response, body={"code": "moderation_blocked"})


class FakeCtx:
    job_id = 4
    dream_id = 1

    def __init__(self, root: Path):
        self.root = root
        self.logger = logging.getLogger("test")

    def report_stage(self, stage):
        pass

    def path_for(self, kind, **ids):
        return self.root / getattr(paths, kind)(self.dream_id, **ids)

    def tmp_dir(self):
        return self.root / paths.job_tmp(self.job_id)


class FakeClient:
    """outcomes 순서대로 예외를 던지거나 이미지를 돌려준다."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.prompts: list[str] = []
        self.images = SimpleNamespace(generate=self._generate)

    def _generate(self, **kwargs):
        self.prompts.append(kwargs["prompt"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(data=[SimpleNamespace(b64_json=outcome)])


@pytest.fixture
def use_client(monkeypatch):
    monkeypatch.setattr(generate, "sleep", lambda _s: None)

    def _use(client):
        monkeypatch.setattr(generate, "get_client", lambda: client)
        return client

    return _use


def test_rejected_then_softened_prompt_succeeds(tmp_path, use_client):
    client = use_client(FakeClient(_rejected(), _png_b64()))
    result = generate.handle_generate_image(FakeCtx(tmp_path), PAYLOAD)

    assert len(client.prompts) == 2
    assert not client.prompts[0].startswith(SOFTEN_PREFIX)
    assert client.prompts[1] == soften_prompt(client.prompts[0])
    assert result["final_prompt"] == client.prompts[1]  # 실제로 쓴 순화 프롬프트를 기록
    assert result["settings"]["policy_softened"] is True
    assert result["attempts"] == 2
    assert (tmp_path / result["image_path"]).exists()


def test_rejected_twice_fails_with_content_policy(tmp_path, use_client):
    client = use_client(FakeClient(_rejected(), _rejected()))
    with pytest.raises(JobError) as e:
        generate.handle_generate_image(FakeCtx(tmp_path), PAYLOAD)
    assert e.value.code == FailureCode.CONTENT_POLICY
    assert len(client.prompts) == 2  # 순화는 한 번만


def test_normal_success_has_no_softened_flag(tmp_path, use_client):
    use_client(FakeClient(_png_b64()))
    result = generate.handle_generate_image(FakeCtx(tmp_path), PAYLOAD)
    assert "policy_softened" not in result["settings"]
    assert not result["final_prompt"].startswith(SOFTEN_PREFIX)


def test_softening_can_be_turned_off(tmp_path, use_client, monkeypatch):
    monkeypatch.setattr(img_cfg, "image_soften_on_policy", False)
    client = use_client(FakeClient(_rejected()))
    with pytest.raises(JobError) as e:
        generate.handle_generate_image(FakeCtx(tmp_path), PAYLOAD)
    assert e.value.code == FailureCode.CONTENT_POLICY
    assert len(client.prompts) == 1


def test_soften_prompt_is_idempotent():
    once = soften_prompt("A dark hallway.")
    assert soften_prompt(once) == once
