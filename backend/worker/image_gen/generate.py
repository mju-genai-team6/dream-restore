"""generate_image 작업 함수 (E2).

장면 하나의 프롬프트로 이미지를 만들어 장면 버전 폴더에 original.png로 저장한다.
작업 하나가 장면 하나를 맡으므로, 한 장면이 실패해도 다른 장면의 작업은 영향을 받지 않는다.

payload (Job API가 넣어 줌):
    scene_id: int              장면 id
    version_no: int            새로 만들 장면 버전 번호 (원본은 덮어쓰지 않음)
    image_prompt_en: str       D가 만든 장면 프롬프트 (app/llm/schemas.py Scene.image_prompt_en)
    characters: list[dict]     (선택) [{"name": "할머니", "appearance": "white hair, pink cardigan, ..."}]
    style_prompt: str          (선택) 꿈 전체 공통 화풍. 없으면 기본 화풍
    confidence_style: str      (선택) E1이 정한 확신도 스타일 문구

결과 (장면 버전에 기록할 값):
    image_path, final_prompt, model, settings, seed, attempts, elapsed_seconds, generated_at
"""
from __future__ import annotations

import base64
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import openai
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.enums import FailureCode, JobStage, JobType
from app.jobs.context import JobContext, JobError
from app.jobs.registry import register
from app.storage import paths
from worker.image_gen.config import image_settings as img_cfg
from worker.image_gen.prompt import Character, build_prompt

# OpenAI가 콘텐츠 정책 위반으로 거절할 때 주는 오류 코드
_CONTENT_POLICY_CODES = {"content_policy_violation", "moderation_blocked"}

# 재시도 사이 대기 (테스트에서 바꿔 끼운다)
sleep: Callable[[float], None] = time.sleep


def image_settings() -> dict[str, Any]:
    return {"size": img_cfg.image_size, "quality": img_cfg.image_quality}


def get_client() -> openai.OpenAI:
    """테스트에서는 가짜 클라이언트로 바꿔 끼운다."""
    if not settings.openai_api_key:
        raise JobError(FailureCode.PROVIDER_ERROR, "OPENAI_API_KEY가 설정되지 않았습니다.")
    return openai.OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.job_timeout_seconds,
        max_retries=0,  # 재시도는 아래 _generate_with_retry에서 실패 사유를 보고 직접 한다
    )


def _parse_characters(raw: Any) -> list[Character]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise JobError(FailureCode.INVALID_INPUT, "characters는 목록이어야 합니다.")
    result = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            raise JobError(FailureCode.INVALID_INPUT, f"characters 항목에 name이 필요합니다: {item!r}")
        result.append(Character(name=str(item["name"]), appearance=str(item.get("appearance") or "")))
    return result


def _parse_payload(payload: dict) -> tuple[int, int, str]:
    try:
        scene_id = int(payload["scene_id"])
        version_no = int(payload["version_no"])
        prompt = str(payload["image_prompt_en"])
    except (KeyError, TypeError, ValueError) as e:
        raise JobError(FailureCode.INVALID_INPUT, f"payload 값이 올바르지 않습니다: {e}") from e
    if version_no < 1 or not prompt.strip():
        raise JobError(FailureCode.INVALID_INPUT, "version_no는 1 이상, image_prompt_en은 비어 있으면 안 됩니다.")
    return scene_id, version_no, prompt


def _request_image(client: openai.OpenAI, prompt: str) -> bytes:
    """API를 한 번 호출하고 PNG 바이트를 돌려준다. 오류는 팀 공통 실패 사유로 바꾼다."""
    try:
        result = client.images.generate(model=img_cfg.openai_image_model, prompt=prompt, n=1, **image_settings())
    except openai.APITimeoutError as e:
        raise JobError(FailureCode.TIMEOUT, "이미지 생성 시간이 초과되었습니다.", retryable=True) from e
    except openai.BadRequestError as e:
        if getattr(e, "code", None) in _CONTENT_POLICY_CODES:
            raise JobError(FailureCode.CONTENT_POLICY, "콘텐츠 정책으로 이미지가 거절되었습니다.") from e
        raise JobError(FailureCode.PROVIDER_ERROR, f"이미지 생성 요청 오류: {e.message}") from e
    except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as e:
        raise JobError(FailureCode.PROVIDER_ERROR, f"이미지 생성 서비스 오류: {e}", retryable=True) from e
    except openai.APIError as e:
        raise JobError(FailureCode.PROVIDER_ERROR, f"이미지 생성 서비스 오류: {e}") from e

    data = result.data[0].b64_json if result.data else None
    if not data:
        raise JobError(FailureCode.PROVIDER_ERROR, "응답에 이미지 데이터가 없습니다.", retryable=True)
    image_bytes = base64.b64decode(data)
    _verify_png(image_bytes)
    return image_bytes


def _verify_png(image_bytes: bytes) -> None:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError) as e:
        raise JobError(FailureCode.PROVIDER_ERROR, "받은 이미지 파일이 손상되었습니다.", retryable=True) from e


def _generate_with_retry(ctx: JobContext, client: openai.OpenAI, prompt: str) -> tuple[bytes, int]:
    """시간 초과·일시적 오류는 img_cfg.image_max_retries번까지 다시 시도한다.
    정책 거부·잘못된 요청은 다시 해도 같으므로 바로 실패 처리한다."""
    max_attempts = 1 + max(img_cfg.image_max_retries, 0)
    for attempt in range(1, max_attempts + 1):
        try:
            return _request_image(client, prompt), attempt
        except JobError as e:
            if not e.retryable or attempt == max_attempts:
                e.message = f"{e.message} (시도 {attempt}회)"
                raise
            wait = 2 ** (attempt - 1)
            ctx.logger.warning("이미지 생성 실패 %s, %s초 뒤 재시도 (%s/%s)", e.code, wait, attempt, max_attempts)
            sleep(wait)
    raise AssertionError("unreachable")


@register(JobType.GENERATE_IMAGE)
def handle_generate_image(ctx: JobContext, payload: dict) -> dict:
    scene_id, version_no, scene_prompt = _parse_payload(payload)
    characters = _parse_characters(payload.get("characters"))

    target = ctx.path_for("scene_original", scene_id=scene_id, version_no=version_no)
    if target.exists():
        raise JobError(FailureCode.INVALID_INPUT, f"이미 있는 장면 버전입니다: v{version_no} (원본은 덮어쓰지 않음)")

    final_prompt = build_prompt(
        scene_prompt,
        characters=characters,
        style=payload.get("style_prompt"),
        confidence_style=payload.get("confidence_style"),
    )

    ctx.report_stage(JobStage.REQUESTING)
    ctx.logger.info("이미지 생성 요청 scene=%s v%s model=%s", scene_id, version_no, img_cfg.openai_image_model)
    started = time.monotonic()
    image_bytes, attempts = _generate_with_retry(ctx, get_client(), final_prompt)
    elapsed = round(time.monotonic() - started, 2)

    ctx.report_stage(JobStage.SAVING)
    tmp_file = ctx.tmp_dir() / f"scene_{scene_id}_v{version_no}.png"
    tmp_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file.write_bytes(image_bytes)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(tmp_file, target)

    return {
        "image_path": str(paths.scene_original(ctx.dream_id, scene_id, version_no)),
        "final_prompt": final_prompt,
        "model": img_cfg.openai_image_model,
        "settings": image_settings(),
        "seed": None,  # OpenAI 이미지 API는 seed를 지원하지 않음
        "attempts": attempts,
        "elapsed_seconds": elapsed,
        "generated_at": datetime.now(UTC).isoformat(),
    }
