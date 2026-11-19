"""이미지 생성(E2) → 확신도 블러·영상 렌더링(E1)을 로컬에서 한 번에 돌려 본다 (E1).

실행: backend 폴더에서  .venv/bin/python scripts/e1_local_pipeline.py [--clean]
- DB·작업 실행기 없이, 실제 작업 함수(handle_generate_image, handle_render_video)를
  작업 레지스트리(HANDLERS)에서 꺼내 순서대로 호출한다.
- OpenAI 이미지 API만 가짜 클라이언트로 바꾼다 (OPENAI_API_KEY 불필요, 비용 없음).
  E2 프롬프트 조합·저장 코드는 그대로 실행되고, 확신도 스타일 문구는 넣지 않는다(confidence_style=None).
- 장면·확신도는 목업 API 데이터(app/services/mock_data.py)와 D 예시(docs/schemas/examples/scenes.json)를 쓴다.
  결과 파일 경로가 목업 API의 image_url·video_url과 같아서, 서버를 띄우면 /storage/... 주소로 바로 열린다.
- --clean: 이전 결과(storage/dreams/{dream_id}, storage/tmp/{job_id})를 지우고 새로 만든다.
  없으면 이미 있는 원본 이미지는 다시 생성하지 않는다 (E2는 원본을 덮어쓰지 않음).
"""

import argparse
import base64
import hashlib
import json
import logging
import shutil
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFilter

import worker.image_gen.generate as image_gen
import worker.render.handler  # noqa: F401  # @register(RENDER_VIDEO) 등록
from app.core.config import settings
from app.core.enums import JobType
from app.jobs.registry import HANDLERS
from app.services import mock_data
from app.storage import paths
from worker.image_gen.config import image_settings as img_cfg

EXAMPLE_SCENES = Path(__file__).resolve().parents[2] / "docs/schemas/examples/scenes.json"
log = logging.getLogger("e1_local")


class LocalJobContext:
    """app/jobs/context.py JobContext 규격의 로컬 구현. 단계는 콘솔에만 찍는다."""

    def __init__(self, job_id: int, dream_id: int):
        self.job_id = job_id
        self.dream_id = dream_id
        self.logger = log
        self.stages: list[str] = []

    def report_stage(self, stage) -> None:
        self.stages.append(str(stage))
        log.info("[job %s] stage=%s", self.job_id, stage)

    def path_for(self, kind: str, **ids) -> Path:
        if kind != "job_tmp":
            ids.setdefault("dream_id", self.dream_id)
        return settings.storage_path / getattr(paths, kind)(**ids)

    def tmp_dir(self) -> Path:
        return settings.storage_path / paths.job_tmp(self.job_id)


def mock_png(prompt: str, size: str) -> bytes:
    """프롬프트마다 다른 색·도형의 그림. 블러 차이가 보이도록 경계가 뚜렷하게 그린다."""
    w, h = (int(v) for v in size.split("x"))
    seed = hashlib.sha256(prompt.encode()).digest()
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    top, bottom = seed[0:3], seed[3:6]
    for y in range(h):  # 세로 그라데이션 배경
        t = y / h
        draw.line([(0, y), (w, y)], fill=tuple(int(a * (1 - t) + b * t) for a, b in zip(top, bottom)))
    for i in range(6):  # 크기·위치가 다른 도형
        x, y, r = seed[8 + i] * w // 255, seed[16 + i] * h // 255, 60 + seed[24 + i]
        color = tuple(seed[(i * 3 + k) % 32] for k in range(3))
        (draw.ellipse if i % 2 else draw.rectangle)([x - r, y - r, x + r, y + r], fill=color, outline="white", width=6)
    img = img.filter(ImageFilter.SMOOTH)
    ImageDraw.Draw(img).text((40, 40), f"MOCK {img_cfg.openai_image_model}\n{prompt[:70]}", fill="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeImagesAPI:
    def generate(self, *, prompt: str, size: str, **_):
        data = base64.b64encode(mock_png(prompt, size)).decode()
        return SimpleNamespace(data=[SimpleNamespace(b64_json=data)])


def load_scenes() -> list[dict]:
    """목업 API의 장면(id·확신도)에 D 예시의 영어 프롬프트를 순서대로 붙인다."""
    prompts = {s["order"]: s["image_prompt_en"] for s in json.loads(EXAMPLE_SCENES.read_text(encoding="utf-8"))["scenes"]}
    return [{**s, "image_prompt_en": prompts[s["order"]]} for s in mock_data.SCENES["scenes"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clean", action="store_true", help="이전 결과를 지우고 새로 만든다")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    dream_id, render_id, render_job_id = mock_data.DREAM_ID, mock_data.RENDER_ID, mock_data.RENDER_JOB_ID
    if args.clean:
        shutil.rmtree(settings.storage_path / f"dreams/{dream_id}", ignore_errors=True)
        shutil.rmtree(settings.storage_path / paths.job_tmp(render_job_id), ignore_errors=True)

    image_gen.get_client = lambda: SimpleNamespace(images=FakeImagesAPI())
    scenes = load_scenes()

    log.info("== 1) generate_image (E2, OpenAI 목업) %d장 ==", len(scenes))
    for i, scene in enumerate(scenes, start=1):
        ctx = LocalJobContext(job_id=100 + i, dream_id=dream_id)
        if ctx.path_for("scene_original", scene_id=scene["scene_id"], version_no=scene["version_no"]).exists():
            log.info("scene %s: 기존 원본 재사용", scene["scene_id"])
            continue
        out = HANDLERS[JobType.GENERATE_IMAGE](ctx, {
            "scene_id": scene["scene_id"],
            "version_no": scene["version_no"],
            "image_prompt_en": scene["image_prompt_en"],
            "confidence_style": None,  # 블러는 E1 후처리에서만 (생성 단계 흐림 금지)
        })
        assert "Memory clarity" not in out["final_prompt"]
        log.info("scene %s → %s", scene["scene_id"], out["image_path"])

    log.info("== 2) render_video (E1) ==")
    ctx = LocalJobContext(job_id=render_job_id, dream_id=dream_id)
    result = HANDLERS[JobType.RENDER_VIDEO](ctx, {
        "render_id": render_id,
        "expected_scene_count": len(scenes),
        "scenes": [
            {k: s[k] for k in ("scene_id", "version_no", "order", "elements")} for s in scenes
        ],
    })

    video = settings.storage_path / result["video_path"]
    assert video.is_file() and video.stat().st_size > 0, video
    assert ctx.stages == ["validating_input", "postprocessing", "composing", "verifying"], ctx.stages
    log.info("== 결과 ==\n%s", json.dumps(result, ensure_ascii=False, indent=2, default=str))
    log.info("영상 주소(목업 API video_url과 동일): %s", paths.public_url(result["video_path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
