"""`render_video` 작업 핸들러 (E1 담당).

규칙 (계획서 3.2, 3.4 및 app/jobs/context.py):
- 작업 함수 규격: `def handle(ctx: JobContext, payload: dict) -> dict`
- 처리 단계 보고 (`ctx.report_stage`):
  1. `JobStage.VALIDATING_INPUT` — 입력·장면 버전·확신도·원본 이미지 확인 및 버전 고정
  2. `JobStage.POSTPROCESSING`   — 장면별 확신도 블러 적용 (`blur_{level}.png`, 재시도 시 기존 파일 재사용)
  3. `JobStage.COMPOSING`        — 임시 폴더(`job_tmp`)에서 FFmpeg Ken Burns + 전환 합성
  4. `JobStage.VERIFYING`        — 출력 영상 검증 후 최종 경로(`render_video`)로 이동
- 실패 시 `JobError(FailureCode.*, message)` 발생.
"""
from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings as app_settings
from app.core.enums import Confidence, FailureCode, JobStage, JobType
from app.jobs.context import JobContext, JobError
from app.jobs.registry import register
from app.storage import paths as storage_paths
from worker.postprocess.blur import (
    DEFAULT_BLUR_SETTINGS,
    BlurSettings,
    PostprocessImageError,
    PostprocessResult,
     _load_rgb_image,
    apply_confidence_blur,
)
from worker.postprocess.confidence import (
    ConfidenceInputError,
    SceneConfidenceResult,
    aggregate_scene_confidence_detail,
    parse_confidence,
)
from worker.render.video import (
    DEFAULT_RENDER_SETTINGS,
    RenderExecutionError,
    RenderInputError,
    RenderSettings,
    RenderTimeoutError,
    SceneRenderInput,
    compose_slideshow_video,
    verify_rendered_video,
)


@dataclass(frozen=True)
class FrozenSceneSpec:
    """렌더링 시작 시점에 고정된 장면 버전 및 확신도 명세."""

    order: int
    scene_id: int
    version_no: int
    scene_version_id: int | None
    original_path: Path
    blur_path: Path
    confidence_level: Confidence
    confidence_detail: SceneConfidenceResult | None
    duration: float | None
    narration_path: Path | None
    narration_duration: float | None


def _safe_path_for(ctx: JobContext, kind: str, **ids: Any) -> Path:
    """`ctx.path_for`를 호출하되, 구현체가 `dream_id` 포함 여부를 다르게 받을 수 있는 경우를 모두 지원한다."""
    try:
        return Path(ctx.path_for(kind, **ids))
    except TypeError:
        ids_without_dream = {k: v for k, v in ids.items() if k != "dream_id"}
        return Path(ctx.path_for(kind, **ids_without_dream))


def _resolve_blur_settings(raw: Mapping[str, Any] | None) -> BlurSettings:
    if not raw:
        return DEFAULT_BLUR_SETTINGS
    try:
        target_size_raw = raw.get("target_size")
        target_size = (
            (int(target_size_raw[0]), int(target_size_raw[1]))
            if isinstance(target_size_raw, (list, tuple)) and len(target_size_raw) == 2
            else None
        )
        return BlurSettings(
            high_radius=float(raw.get("high_radius", DEFAULT_BLUR_SETTINGS.high_radius)),
            medium_radius=float(raw.get("medium_radius", DEFAULT_BLUR_SETTINGS.medium_radius)),
            low_radius=float(raw.get("low_radius", DEFAULT_BLUR_SETTINGS.low_radius)),
            reference_long_edge=int(
                raw.get("reference_long_edge", DEFAULT_BLUR_SETTINGS.reference_long_edge)
            ),
            normalize_by_resolution=bool(
                raw.get("normalize_by_resolution", DEFAULT_BLUR_SETTINGS.normalize_by_resolution)
            ),
            target_size=target_size,
        )
    except (TypeError, ValueError) as exc:
        raise JobError(
            FailureCode.INVALID_INPUT,
            f"블러 후처리 설정값(blur_settings)이 올바르지 않습니다: {exc}",
        ) from exc


def _resolve_render_settings(raw: Mapping[str, Any] | None) -> RenderSettings:
    if not raw:
        return DEFAULT_RENDER_SETTINGS
    try:
        return RenderSettings(
            width=int(raw.get("width", DEFAULT_RENDER_SETTINGS.width)),
            height=int(raw.get("height", DEFAULT_RENDER_SETTINGS.height)),
            fps=int(raw.get("fps", DEFAULT_RENDER_SETTINGS.fps)),
            default_scene_duration=float(
                raw.get("default_scene_duration", DEFAULT_RENDER_SETTINGS.default_scene_duration)
            ),
            transition_duration=float(
                raw.get("transition_duration", DEFAULT_RENDER_SETTINGS.transition_duration)
            ),
            transition_type=str(
                raw.get("transition_type", DEFAULT_RENDER_SETTINGS.transition_type)
            ),
            max_zoom=float(raw.get("max_zoom", DEFAULT_RENDER_SETTINGS.max_zoom)),
            narration_padding=float(
                raw.get("narration_padding", DEFAULT_RENDER_SETTINGS.narration_padding)
            ),
            crf=int(raw.get("crf", DEFAULT_RENDER_SETTINGS.crf)),
            preset=str(raw.get("preset", DEFAULT_RENDER_SETTINGS.preset)),
        )
    except (TypeError, ValueError) as exc:
        raise JobError(
            FailureCode.INVALID_INPUT,
            f"렌더링 설정값(render_settings)이 올바르지 않습니다: {exc}",
        ) from exc


def _resolve_scene_confidence(
    scene_item: Mapping[str, Any],
    dream_elements: Sequence[Mapping[str, Any]] | None,
) -> tuple[Confidence, SceneConfidenceResult | None]:
    """장면 데이터의 요소 목록 또는 명시된 확신도로부터 장면 확신도를 계산·검증한다."""
    scene_elements = scene_item.get("elements")
    element_names = scene_item.get("element_names")
    explicit_level = scene_item.get("confidence_level")

    detail: SceneConfidenceResult | None = None
    try:
        if scene_elements is not None:
            detail = aggregate_scene_confidence_detail(scene_elements)
        elif dream_elements is not None and element_names is not None:
            detail = aggregate_scene_confidence_detail(
                dream_elements,
                scene_element_names=element_names,
            )
    except ConfidenceInputError as exc:
        raise JobError(FailureCode.INVALID_INPUT, str(exc)) from exc

    if explicit_level is not None:
        try:
            parsed_explicit = parse_confidence(explicit_level)
        except ConfidenceInputError as exc:
            raise JobError(FailureCode.INVALID_INPUT, str(exc)) from exc
        if detail is not None and detail.confidence_level != parsed_explicit:
            raise JobError(
                FailureCode.INVALID_INPUT,
                f"장면 {scene_item.get('scene_id')}의 명시된 확신도({parsed_explicit.value})와 "
                f"요소 집계 결과({detail.confidence_level.value})가 일치하지 않습니다.",
            )
        return parsed_explicit, detail

    if detail is not None:
        return detail.confidence_level, detail

    raise JobError(
        FailureCode.INVALID_INPUT,
        f"장면 {scene_item.get('scene_id')}에 확신도(confidence_level 또는 elements) 정보가 없습니다.",
    )


def _validate_and_freeze_scenes(
    ctx: JobContext,
    payload: Mapping[str, Any],
) -> tuple[int, list[FrozenSceneSpec], BlurSettings, RenderSettings]:
    """1단계(`validating_input`): 입력 페이로드와 원본 이미지 파일을 검증하고 장면 버전을 고정한다."""
    if not isinstance(payload, Mapping):
        raise JobError(FailureCode.INVALID_INPUT, "작업 payload는 딕셔너리 형식이어야 합니다.")

    raw_render_id = payload.get("render_id", ctx.job_id)
    try:
        render_id = int(raw_render_id)
        if render_id <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise JobError(
            FailureCode.INVALID_INPUT,
            f"유효하지 않은 render_id입니다: {raw_render_id!r}",
        ) from exc

    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, Sequence) or isinstance(raw_scenes, (str, bytes)) or not raw_scenes:
        raise JobError(FailureCode.INVALID_INPUT, "렌더링할 장면 목록(scenes)이 비어 있습니다.")

    expected_count = payload.get("expected_scene_count")
    if expected_count is not None and len(raw_scenes) != int(expected_count):
        raise JobError(
            FailureCode.INVALID_INPUT,
            f"전달된 장면 수({len(raw_scenes)})가 기대 장면 수({expected_count})와 일치하지 않습니다.",
        )

    blur_settings = _resolve_blur_settings(payload.get("blur_settings"))
    render_settings = _resolve_render_settings(payload.get("render_settings"))
    dream_elements = payload.get("elements")

    frozen: list[FrozenSceneSpec] = []
    seen_scene_ids: set[int] = set()

    for idx, item in enumerate(raw_scenes, start=1):
        if not isinstance(item, Mapping):
            raise JobError(FailureCode.INVALID_INPUT, f"{idx}번째 장면 항목 형식이 올바르지 않습니다.")

        try:
            scene_id = int(item["scene_id"])
            version_no = int(item.get("version_no", 1))
            order = int(item.get("order", idx))
            if scene_id <= 0 or version_no <= 0 or order <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise JobError(
                FailureCode.INVALID_INPUT,
                f"{idx}번째 장면의 scene_id 또는 version_no가 누락되었거나 올바르지 않습니다.",
            ) from exc

        if scene_id in seen_scene_ids:
            raise JobError(
                FailureCode.INVALID_INPUT,
                f"중복된 scene_id({scene_id})가 포함되어 있습니다.",
            )
        seen_scene_ids.add(scene_id)

        scene_version_id_raw = item.get("scene_version_id", item.get("id"))
        scene_version_id = int(scene_version_id_raw) if scene_version_id_raw is not None else None

        level, conf_detail = _resolve_scene_confidence(item, dream_elements)

        if item.get("image_path"):
            original_path = Path(str(item["image_path"]))
        else:
            original_path = _safe_path_for(
                ctx,
                "scene_original",
                dream_id=ctx.dream_id,
                scene_id=scene_id,
                version_no=version_no,
            )

        # 원본 이미지 존재 및 손상 여부 즉시 확인 (필수 이미지 누락 시 생략하지 않고 실패 보고)
        try:
            _load_rgb_image(original_path)
        except PostprocessImageError as exc:
            raise JobError(
                FailureCode.INVALID_INPUT,
                f"장면 {scene_id}(v{version_no}) 원본 이미지 오류: {exc}",
            ) from exc

        if item.get("blur_path"):
            blur_path = Path(str(item["blur_path"]))
        else:
            blur_path = _safe_path_for(
                ctx,
                "scene_blur",
                dream_id=ctx.dream_id,
                scene_id=scene_id,
                version_no=version_no,
                level=level.value,
            )

        narration_path: Path | None = None
        if item.get("narration_path"):
            narration_path = Path(str(item["narration_path"]))
        else:
            try:
                candidate_nar = _safe_path_for(
                    ctx,
                    "scene_narration",
                    dream_id=ctx.dream_id,
                    scene_id=scene_id,
                    version_no=version_no,
                )
                if candidate_nar.exists() and candidate_nar.is_file():
                    narration_path = candidate_nar
            except (AttributeError, TypeError, ValueError, OSError):
                narration_path = None

        raw_dur = item.get("duration")
        duration = float(raw_dur) if raw_dur is not None else None
        raw_nar_dur = item.get("narration_duration")
        narration_duration = float(raw_nar_dur) if raw_nar_dur is not None else None

        frozen.append(
            FrozenSceneSpec(
                order=order,
                scene_id=scene_id,
                version_no=version_no,
                scene_version_id=scene_version_id,
                original_path=original_path,
                blur_path=blur_path,
                confidence_level=level,
                confidence_detail=conf_detail,
                duration=duration,
                narration_path=narration_path,
                narration_duration=narration_duration,
            )
        )

    frozen.sort(key=lambda s: s.order)
    expected_orders = list(range(1, len(frozen) + 1))
    actual_orders = [s.order for s in frozen]
    if actual_orders != expected_orders:
        raise JobError(
            FailureCode.INVALID_INPUT,
            f"장면 순서(order)는 1부터 연속되어야 합니다: {actual_orders}",
        )

    return render_id, frozen, blur_settings, render_settings


@register(JobType.RENDER_VIDEO)
def handle_render_video(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    """`render_video` 작업을 실행한다.

    단계:
    1. `validating_input`: 입력 검증 및 렌더링 대상 장면 버전/설정 고정
    2. `postprocessing`: 장면별 확신도 블러 적용 (재시도 시 기존 후처리 이미지 재사용)
    3. `composing`: 임시 폴더에서 FFmpeg Ken Burns + Crossfade 영상 합성
    4. `verifying`: 출력 영상 검증 및 최종 `render_video` 경로로 원자적 이동
    """
    # 1. 입력 검증 및 장면 버전 고정
    ctx.report_stage(JobStage.VALIDATING_INPUT)
    render_id, frozen_scenes, blur_settings, render_settings = _validate_and_freeze_scenes(
        ctx, payload
    )
    reuse_postprocessed = bool(payload.get("reuse_postprocessed", True))
    timeout_sec = float(payload.get("timeout_seconds", app_settings.job_timeout_seconds))

    ctx.logger.info(
        "render_video 시작 (dream_id=%s, render_id=%s, scenes=%d)",
        ctx.dream_id,
        render_id,
        len(frozen_scenes),
    )

    # 2. Pillow 확신도 블러 후처리
    ctx.report_stage(JobStage.POSTPROCESSING)
    postprocess_results: list[PostprocessResult] = []
    for spec in frozen_scenes:
        try:
            pp_res = apply_confidence_blur(
                source_path=spec.original_path,
                output_path=spec.blur_path,
                confidence_level=spec.confidence_level,
                settings=blur_settings,
                scene_id=spec.scene_id,
                version_no=spec.version_no,
                reuse_existing=reuse_postprocessed,
            )
            postprocess_results.append(pp_res)
        except PostprocessImageError as exc:
            raise JobError(
                FailureCode.INVALID_INPUT,
                f"장면 {spec.scene_id}(v{spec.version_no}) 블러 후처리 실패: {exc}",
            ) from exc
        except Exception as exc:
            raise JobError(
                FailureCode.RENDER_FAILED,
                f"장면 {spec.scene_id}(v{spec.version_no}) 후처리 중 오류 발생: {exc}",
                retryable=True,
            ) from exc

    # 3. FFmpeg 슬라이드 영상 합성 (임시 폴더에 생성)
    ctx.report_stage(JobStage.COMPOSING)
    tmp_dir = Path(ctx.tmp_dir())
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_video_path = tmp_dir / f"render_{render_id}.mp4"

    render_inputs = [
        SceneRenderInput(
            order=spec.order,
            scene_id=spec.scene_id,
            version_no=spec.version_no,
            image_path=spec.blur_path,
            duration=spec.duration,
            narration_path=spec.narration_path,
            narration_duration=spec.narration_duration,
        )
        for spec in frozen_scenes
    ]

    try:
        composition = compose_slideshow_video(
            scenes=render_inputs,
            output_path=tmp_video_path,
            settings=render_settings,
            timeout=timeout_sec,
        )
    except RenderTimeoutError as exc:
        raise JobError(FailureCode.TIMEOUT, str(exc), retryable=True) from exc
    except RenderInputError as exc:
        raise JobError(FailureCode.INVALID_INPUT, str(exc)) from exc
    except RenderExecutionError as exc:
        raise JobError(FailureCode.RENDER_FAILED, str(exc), retryable=True) from exc

    # 4. 결과 검증 및 최종 저장 경로로 이동
    ctx.report_stage(JobStage.VERIFYING)
    final_video_path = _safe_path_for(
        ctx,
        "render_video",
        dream_id=ctx.dream_id,
        render_id=render_id,
    )
    final_video_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(tmp_video_path), str(final_video_path))
        verification = verify_rendered_video(
            final_video_path,
            expected_width=render_settings.width,
            expected_height=render_settings.height,
            expected_duration=composition.expected_duration,
            duration_tolerance=render_settings.duration_tolerance,
        )
    except RenderTimeoutError as exc:
        raise JobError(FailureCode.TIMEOUT, str(exc), retryable=True) from exc
    except (RenderExecutionError, OSError) as exc:
        raise JobError(
            FailureCode.RENDER_FAILED,
            f"최종 영상 파일 이동 및 검증에 실패했습니다: {exc}",
            retryable=True,
        ) from exc

    rel_video_path = storage_paths.render_video(ctx.dream_id, render_id)
    scene_version_ids = [
        spec.scene_version_id if spec.scene_version_id is not None else spec.scene_id
        for spec in frozen_scenes
    ]

    scene_records: list[dict[str, Any]] = []
    for spec, pp_res, dur, start_off in zip(
        frozen_scenes,
        postprocess_results,
        composition.scene_durations,
        composition.scene_start_offsets,
        strict=True,
    ):
        rel_blur = storage_paths.scene_blur(
            ctx.dream_id,
            spec.scene_id,
            spec.version_no,
            spec.confidence_level.value,
        )
        record: dict[str, Any] = {
            "order": spec.order,
            "scene_id": spec.scene_id,
            "version_no": spec.version_no,
            "scene_version_id": spec.scene_version_id,
            "confidence_level": spec.confidence_level.value,
            "base_radius": pp_res.base_radius,
            "blur_radius": pp_res.blur_radius,
            "blur_image_path": str(rel_blur),
            "reused_existing_blur": pp_res.reused_existing,
            "duration": dur,
            "start_offset": start_off,
        }
        if spec.confidence_detail is not None:
            record["mean_confidence_score"] = spec.confidence_detail.mean_score
            record["element_confidences"] = [
                el.to_dict() for el in spec.confidence_detail.elements
            ]
        scene_records.append(record)

    combined_settings = {
        "blur": blur_settings.to_metadata(),
        "render": render_settings.to_metadata(),
    }

    ctx.logger.info(
        "render_video 완료 (dream_id=%s, render_id=%s, duration=%.2fs, path=%s)",
        ctx.dream_id,
        render_id,
        verification.duration,
        rel_video_path,
    )

    return {
        "render_id": render_id,
        "video_path": str(rel_video_path),
        "video_url": storage_paths.public_url(rel_video_path),
        "width": verification.width,
        "height": verification.height,
        "fps": verification.fps,
        "duration": verification.duration,
        "has_audio": verification.has_audio,
        "scene_version_ids": scene_version_ids,
        "scenes": scene_records,
        "postprocess_settings": combined_settings,
    }
