"""generate_image 작업 연결 (C-S3-02). 실제 핸들러는 E2(worker/image_gen/generate.py), 저장은 후처리에서 한다.

- payload는 E2 입력 형식(image_payload). confidence_level은 항상 넣고, 스타일 문구는 설정이 켜져 있을 때만 넣는다
- 성공 후처리: 꿈 행을 잠근 뒤 결과와 장면 확신도를 한 번에 저장하고, 조건이 맞으면 images_ready
- 실패 후처리: 장면 버전 failed. 꿈은 scenes_ready 그대로 두고 POST /dreams/{id}/images/retry로 다시 만든다
- settings.image_generation_mode가 fake면 서버 시작 때 가짜 핸들러를 등록한다(install_image_handler)
"""
import logging
import shutil
import time
from datetime import UTC, datetime
from typing import Literal

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import DreamStatus, FailureCode, JobStage, JobType
from app.jobs.context import JobContext, JobError
from app.jobs.registry import HANDLERS, Handler, on_failure, on_success
from app.models import Scene
from app.models.job import Job
from app.models.scene import SceneVersion
from app.repositories import dreams as dream_repo
from app.repositories import extractions as extraction_repo
from app.repositories import jobs as job_repo
from app.repositories import scenes as scene_repo
from app.services.state_machine import ensure_transition
from app.storage import paths
from worker.image_gen.config import image_settings as img_cfg
from worker.image_gen.generate import handle_generate_image
from worker.image_gen.prompt import Character, build_prompt
from worker.postprocess.confidence import (
    ConfidenceInputError,
    aggregate_scene_confidence,
    confidence_style_for,
)

ImageMode = Literal["fake", "real"]

FAKE_MODEL = "fake"
MISSING_VERSION_MESSAGE = "이미지를 저장할 장면 버전이 없습니다."
ALREADY_SAVED_MESSAGE = "이미 이미지가 저장된 장면 버전입니다."
FAKE_COLORS = [(72, 61, 139), (46, 139, 87), (178, 34, 34), (218, 165, 32), (70, 130, 180), (199, 21, 133)]

logger = logging.getLogger(__name__)


def image_payload(
    db: Session, dream_id: int, version: SceneVersion, prompt_en: str, characters: list[dict]
) -> dict:
    """E2 handle_generate_image 입력. 장면 생성 후처리와 다시 생성 API가 같이 쓴다.

    장면 확신도 단계는 성공 후처리와 같은 _scene_confidence로 구한다. 계산할 수 없으면 None이다.
    confidence_style은 settings.confidence_prompt_style이 켜져 있고 단계가 있을 때만 문구가 된다.
    """
    level = _scene_confidence(db, dream_id, version)
    style = None
    if settings.confidence_prompt_style and level is not None:
        try:
            style = confidence_style_for(level)
        except ConfidenceInputError as exc:
            logger.warning("장면 버전 %s의 확신도 스타일 문구를 만들지 못해 비워 둡니다: %s", version.id, exc)
    return {
        "scene_id": version.scene_id,
        "version_no": version.version_no,
        "image_prompt_en": prompt_en,
        "characters": characters,
        "confidence_level": level,
        "confidence_style": style,
    }


def _scene_confidence(db: Session, dream_id: int, version: SceneVersion) -> str | None:
    """장면 요소의 확신도를 E1 규칙으로 집계한다. 계산할 수 없으면(예: 감정만 있는 장면) None."""
    ids = {int(element_id) for element_id in version.element_ids or []}
    elements = [row for row in extraction_repo.list_elements(db, dream_id) if row.id in ids]
    try:
        return aggregate_scene_confidence(elements).value
    except ConfidenceInputError as exc:
        logger.warning("장면 버전 %s의 장면 확신도를 계산하지 못해 비워 둡니다: %s", version.id, exc)
        return None


@on_success(JobType.GENERATE_IMAGE)
def save_image(db: Session, job: Job, result: dict) -> None:
    """실행기가 이 함수 뒤에 succeeded와 함께 commit한다. 여기서 commit하지 않는다.

    꿈 행을 먼저 잠근다. 마지막 두 장면이 동시에 끝나도 뒤 작업은 앞 작업의 commit을 본 뒤
    all_images_done을 읽으므로, 둘 다 False로 보고 전이를 놓치는 일이 없다.
    저장한 버전이 현재 버전이 아니면 그 버전으로 바꾼다. 꿈 상태는 바꾸지 않는다.
    """
    dream_repo.lock_dream(db, job.dream_id)
    version = scene_repo.get_scene_version(db, job.target_id) if job.target_id else None
    if version is None:
        raise JobError(FailureCode.INVALID_INPUT, MISSING_VERSION_MESSAGE)
    saved = scene_repo.save_image_result(
        db,
        version.id,
        final_prompt=result["final_prompt"],
        model=result["model"],
        settings=result["settings"],
        seed=result.get("seed"),
        image_path=result["image_path"],
        generated_at=datetime.fromisoformat(result["generated_at"]),
        confidence_level=_scene_confidence(db, job.dream_id, version),
    )
    if not saved:
        raise JobError(FailureCode.INVALID_INPUT, ALREADY_SAVED_MESSAGE)

    # 수정으로 만든 버전은 아직 현재 버전이 아니다. 이미지가 성공하면 그때 교체한다. 꿈 상태는 바꾸지 않는다.
    scene = db.get(Scene, version.scene_id)
    if scene is not None and scene.current_version_id != version.id:
        scene_repo.set_current_version(db, scene.id, version.id)

    maybe_mark_images_ready(db, job.dream_id, ignore_job_id=job.id)


def maybe_mark_images_ready(db: Session, dream_id: int, *, ignore_job_id: int | None = None) -> None:
    """이미지가 모두 성공하고 진행 중인 나레이션이 없을 때만 scenes_ready를 images_ready로 바꾼다.

    꿈 행을 잠근 뒤 조건을 읽는다. 동시에 끝나도 뒤 작업은 앞 작업의 commit을 본 다음에 조건을 보므로
    전이는 한 번이다. on_success 안의 현재 작업은 아직 running이라 ignore_job_id로 진행 중에서 뺀다.
    나레이션 작업이 없으면(기능이 꺼진 경우) 이미지 조건만 남는다.
    이미 scenes_ready가 아니면 로그만 남기고 작업을 실패로 만들지 않는다.
    """
    dream_repo.lock_dream(db, dream_id)
    if not scene_repo.all_images_done(db, dream_id):
        return
    if any(
        row.type == JobType.GENERATE_NARRATION and row.id != ignore_job_id
        for row in job_repo.get_active_jobs(db, dream_id)
    ):
        return
    ensure_transition(DreamStatus.SCENES_READY, DreamStatus.IMAGES_READY)
    if not dream_repo.transition_status(db, dream_id, DreamStatus.SCENES_READY, DreamStatus.IMAGES_READY):
        logger.info("꿈 %s는 이미 scenes_ready가 아니어서 상태를 바꾸지 않습니다.", dream_id)


@on_failure(JobType.GENERATE_IMAGE)
def mark_image_failed(db: Session, job: Job, error_code: str | None, error_message: str) -> None:
    """장면 버전만 failed로 바꾼다. 꿈 상태는 scenes_ready 그대로 둔다."""
    if job.target_id is not None:
        scene_repo.mark_scene_version_failed(db, job.target_id)


def _scene_order(scene_id: int) -> int:
    # 핸들러 인자에 순서가 없어 짧게 읽는다. runner가 이 모듈을 import하므로 함수 안에서 불러온다
    from app.jobs import runner

    with runner.session_factory() as db:
        scene = db.get(Scene, scene_id)
        return 0 if scene is None else scene.order


def _fake_png(dream_id: int, order: int, version_no: int, confidence_level: str | None) -> Image.Image:
    width, height = (int(n) for n in img_cfg.image_size.split("x"))
    image = Image.new("RGB", (width, height), FAKE_COLORS[(order - 1) % len(FAKE_COLORS)])
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=height // 12)
    level = confidence_level if confidence_level else "none"
    lines = ["FAKE IMAGE", f"dream {dream_id} · scene {order} · v{version_no} · {level}"]
    draw.multiline_text(
        (width // 2, height // 2), "\n".join(lines), fill=(255, 255, 255), font=font, anchor="mm", align="center"
    )
    return image


def fake_generate_image(ctx: JobContext, payload: dict) -> dict:
    """E2 핸들러와 같은 입력·반환 형식. 이미지 API 대신 단색 PNG를 scene_original 경로에 저장한다."""
    started = time.monotonic()
    scene_id = int(payload["scene_id"])
    version_no = int(payload["version_no"])
    target = ctx.path_for("scene_original", scene_id=scene_id, version_no=version_no)
    if target.exists():
        raise JobError(FailureCode.INVALID_INPUT, f"이미 있는 장면 버전입니다: v{version_no} (원본은 덮어쓰지 않음)")
    characters = [
        Character(name=str(item["name"]), appearance=str(item.get("appearance") or ""))
        for item in payload.get("characters") or []
    ]
    final_prompt = build_prompt(str(payload["image_prompt_en"]), characters=characters, style=payload.get("style_prompt"))

    ctx.report_stage(JobStage.REQUESTING)
    level = payload.get("confidence_level")
    image = _fake_png(ctx.dream_id, _scene_order(scene_id), version_no, level if isinstance(level, str) else None)

    ctx.report_stage(JobStage.SAVING)
    tmp_file = ctx.tmp_dir() / f"scene_{scene_id}_v{version_no}.png"
    tmp_file.parent.mkdir(parents=True, exist_ok=True)
    image.save(tmp_file, format="PNG")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(tmp_file, target)

    return {
        "image_path": str(paths.scene_original(ctx.dream_id, scene_id, version_no)),
        "final_prompt": final_prompt,
        "model": FAKE_MODEL,
        "settings": {"size": img_cfg.image_size, "quality": img_cfg.image_quality},
        "seed": None,
        "attempts": 1,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def install_image_handler(mode: ImageMode) -> Handler:
    """generate_image 핸들러를 모드에 맞게 등록한다. real일 때만 E2 핸들러(실제 이미지 API)를 쓴다."""
    handler: Handler = handle_generate_image if mode == "real" else fake_generate_image
    HANDLERS[JobType.GENERATE_IMAGE] = handler
    return handler
