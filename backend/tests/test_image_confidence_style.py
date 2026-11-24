"""generate_image가 payload의 confidence_style을 프롬프트에 넣는지 확인한다. 실제 이미지 API는 부르지 않는다."""
import base64
import logging
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.enums import FailureCode
from app.jobs.context import JobError
from app.storage import paths
from worker.image_gen import generate


def _png_b64() -> str:
    buf = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeCtx:
    job_id = 3
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
    def __init__(self):
        self.prompts: list[str] = []
        self.images = SimpleNamespace(generate=self._generate)

    def _generate(self, **kwargs):
        self.prompts.append(kwargs["prompt"])
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_png_b64())])


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(generate, "get_client", lambda: fake)
    return fake


PAYLOAD = {"scene_id": 2, "version_no": 1, "image_prompt_en": "A grandmother hands over a yellow umbrella"}


def test_confidence_style_is_appended_last(tmp_path, client):
    result = generate.handle_generate_image(
        FakeCtx(tmp_path), {**PAYLOAD, "confidence_style": "slightly hazy, soft focus"}
    )
    assert client.prompts == [result["final_prompt"]]
    assert result["final_prompt"].endswith("Memory clarity: slightly hazy, soft focus.")


@pytest.mark.parametrize("value", [None, "", "   "])
def test_without_confidence_style_prompt_is_unchanged(tmp_path, client, value):
    payload = dict(PAYLOAD) if value is None else {**PAYLOAD, "confidence_style": value}
    result = generate.handle_generate_image(FakeCtx(tmp_path), payload)
    assert "Memory clarity" not in result["final_prompt"]


def test_non_string_confidence_style_is_invalid_input(tmp_path, client):
    with pytest.raises(JobError) as exc:
        generate.handle_generate_image(FakeCtx(tmp_path), {**PAYLOAD, "confidence_style": 3})
    assert exc.value.code == FailureCode.INVALID_INPUT
    assert client.prompts == []
