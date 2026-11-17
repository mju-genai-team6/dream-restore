"""E1 확신도 블러 후처리(`worker/postprocess`) 및 영상 렌더링(`worker/render`) 테스트."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.core.enums import Confidence, FailureCode, JobStage, JobType
from app.jobs.context import JobError
from app.jobs.registry import HANDLERS
from app.storage import paths as storage_paths
from worker.image_gen.prompt import build_prompt
from worker.postprocess import (
    CONFIDENCE_STYLE_PROMPTS,
    BlurSettings,
    ConfidenceInputError,
    PostprocessImageError,
    aggregate_scene_confidence,
    aggregate_scene_confidence_detail,
    apply_confidence_blur,
    confidence_style_for,
    level_for_mean_score,
    postprocess_scene_for_storage,
    score_for_confidence,
)
from worker.render import (
    RenderExecutionError,
    RenderSettings,
    RenderTimeoutError,
    SceneRenderInput,
    calculate_scene_timeline,
    compose_slideshow_video,
    handle_render_video,
    resolve_ffmpeg_binary,
    verify_rendered_video,
)
from worker.render.video import _build_filter_complex


class FakeJobContext:
    """테스트용 JobContext 구현체 (`app/jobs/context.py` 프로토콜 준수)."""

    def __init__(self, storage_root: Path, dream_id: int = 10, job_id: int = 99) -> None:
        self.storage_root = storage_root
        self.dream_id = dream_id
        self.job_id = job_id
        self.logger = logging.getLogger("test.render_video")
        self.stages: list[JobStage] = []

    def report_stage(self, stage: JobStage) -> None:
        self.stages.append(stage)

    def path_for(self, kind: str, **ids) -> Path:
        fn = getattr(storage_paths, kind)
        if "dream_id" not in ids:
            ids["dream_id"] = self.dream_id
        rel = fn(**ids)
        return self.storage_root / rel

    def tmp_dir(self) -> Path:
        return self.storage_root / storage_paths.job_tmp(self.job_id)


def _make_checker_image(path: Path, size: tuple[int, int] = (640, 360)) -> Path:
    """블러 전후 선명도 비교를 위해 격자·도형 패턴 이미지를 생성한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    img = Image.new("RGB", (w, h), (25, 30, 45))
    draw = ImageDraw.Draw(img)
    step = 40
    for y in range(0, h, step):
        for x in range(0, w, step):
            if ((x // step) + (y // step)) % 2 == 0:
                draw.rectangle([x, y, x + step - 1, y + step - 1], fill=(235, 210, 90))
    draw.ellipse([w // 4, h // 4, (w * 3) // 4, (h * 3) // 4], fill=(220, 90, 120), outline=(255, 255, 255), width=4)
    img.save(path, format="PNG")
    return path


def _mean_gradient_energy(path: Path) -> float:
    with Image.open(path) as img:
        gray = img.convert("L")
        w, h = gray.size
        px = gray.load()
        assert px is not None
        total = 0.0
        count = 0
        for y in range(h - 1):
            for x in range(w - 1):
                dx = float(px[x + 1, y]) - float(px[x, y])
                dy = float(px[x, y + 1]) - float(px[x, y])
                total += dx * dx + dy * dy
                count += 1
        return total / max(1, count)


# ---------------------------------------------------------------------------
# 1. 장면 확신도 집계 테스트
# ---------------------------------------------------------------------------


def test_confidence_scores_and_boundaries():
    assert score_for_confidence("high") == 2
    assert score_for_confidence(Confidence.MEDIUM) == 1
    assert score_for_confidence("low") == 0

    assert level_for_mean_score(0.0) == Confidence.LOW
    assert level_for_mean_score(0.49) == Confidence.LOW
    assert level_for_mean_score(0.5) == Confidence.MEDIUM
    assert level_for_mean_score(1.49) == Confidence.MEDIUM
    assert level_for_mean_score(1.5) == Confidence.HIGH
    assert level_for_mean_score(2.0) == Confidence.HIGH


def test_aggregate_excludes_emotions_and_preserves_elements():
    elements = [
        {"id": 1, "type": "person", "name": "할머니", "confidence": "high"},
        {"id": 2, "type": "place", "name": "학교 복도", "confidence": "low"},
        {"id": 3, "type": "object", "name": "우산", "confidence": "high"},
        {"id": 4, "type": "emotion", "name": "안도감", "confidence": "low"},
    ]
    detail = aggregate_scene_confidence_detail(
        elements,
        scene_element_names=["학교 복도", "할머니", "우산", "안도감"],
    )
    # 시각 요소: 할머니(2) + 학교 복도(0) + 우산(2) = 4 / 3 = 1.3333 -> medium
    assert detail.confidence_level == Confidence.MEDIUM
    assert detail.visual_element_count == 3
    assert detail.excluded_emotion_count == 1
    assert detail.mean_score == pytest.approx(4 / 3, rel=1e-3)
    # 원본 요소 4개(감정 포함) 모두 보존
    assert len(detail.elements) == 4
    emotion_rec = next(e for e in detail.elements if e.name == "안도감")
    assert emotion_rec.is_visual is False
    assert emotion_rec.confidence == Confidence.LOW


@pytest.mark.parametrize(
    "bad_elements",
    [
        [],
        [{"type": "person", "name": "할머니", "confidence": None}],
        [{"type": "person", "name": "할머니", "confidence": ""}],
        [{"type": "person", "name": "할머니", "confidence": "very_high"}],
        [{"type": "weather", "name": "비", "confidence": "high"}],
        [{"type": "emotion", "name": "두려움", "confidence": "high"}],  # 시각 요소 0개
    ],
)
def test_aggregate_rejects_invalid_or_missing_confidence(bad_elements):
    with pytest.raises(ConfidenceInputError):
        aggregate_scene_confidence(bad_elements)


def test_aggregate_rejects_unknown_scene_element_name():
    elements = [{"type": "place", "name": "바다", "confidence": "high"}]
    with pytest.raises(ConfidenceInputError, match="찾을 수 없습니다"):
        aggregate_scene_confidence(elements, scene_element_names=["없는 장소"])


# ---------------------------------------------------------------------------
# 2. Pillow 블러 후처리 테스트
# ---------------------------------------------------------------------------


def test_blur_levels_preserve_original_and_order_sharpness(tmp_path: Path):
    orig = _make_checker_image(tmp_path / "original.png", size=(640, 360))
    orig_bytes = orig.read_bytes()

    high_out = tmp_path / "blur_high.png"
    med_out = tmp_path / "blur_medium.png"
    low_out = tmp_path / "blur_low.png"

    res_high = apply_confidence_blur(orig, high_out, Confidence.HIGH)
    res_med = apply_confidence_blur(orig, med_out, Confidence.MEDIUM)
    res_low = apply_confidence_blur(orig, low_out, Confidence.LOW)

    # 원본 파일이 변경되지 않았는지 확인
    assert orig.read_bytes() == orig_bytes
    assert res_high.blur_radius == 0.0
    assert 0.0 < res_med.blur_radius < res_low.blur_radius

    s_high = _mean_gradient_energy(high_out)
    s_med = _mean_gradient_energy(med_out)
    s_low = _mean_gradient_energy(low_out)
    assert s_high > s_med > s_low


def test_blur_is_deterministic_and_supports_reuse(tmp_path: Path):
    orig = _make_checker_image(tmp_path / "original.png")
    out1 = tmp_path / "out1.png"
    out2 = tmp_path / "out2.png"
    settings = BlurSettings(high_radius=0.0, medium_radius=6.0, low_radius=16.0)

    r1 = apply_confidence_blur(orig, out1, "medium", settings)
    r2 = apply_confidence_blur(orig, out2, "medium", settings)
    assert out1.read_bytes() == out2.read_bytes()
    assert r1.reused_existing is False
    assert r2.reused_existing is False

    # 수동 재시도 시 기존 후처리 이미지 재사용 확인
    r_reused = apply_confidence_blur(orig, out1, "medium", settings, reuse_existing=True)
    assert r_reused.reused_existing is True


def test_blur_forbids_overwriting_original_and_corrupt_source(tmp_path: Path):
    orig = _make_checker_image(tmp_path / "original.png")
    with pytest.raises(PostprocessImageError, match="덮어쓸 수 없습니다"):
        apply_confidence_blur(orig, orig, Confidence.LOW)

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not-an-image")
    with pytest.raises(PostprocessImageError):
        apply_confidence_blur(corrupt, tmp_path / "out.png", Confidence.LOW)


def test_postprocess_scene_for_storage_follows_path_rules(tmp_path: Path):
    rel_orig = storage_paths.scene_original(1, 2, 1)
    _make_checker_image(tmp_path / rel_orig)

    res = postprocess_scene_for_storage(
        storage_root=tmp_path,
        dream_id=1,
        scene_id=2,
        version_no=1,
        confidence_level=Confidence.LOW,
    )
    expected_rel = str(storage_paths.scene_blur(1, 2, 1, "low"))
    assert res.output_path == expected_rel
    assert (tmp_path / expected_rel).is_file()


# ---------------------------------------------------------------------------
# 3. FFmpeg 슬라이드 영상 렌더링 및 render_video 핸들러 테스트
# ---------------------------------------------------------------------------


def _require_ffmpeg() -> str:
    """로컬 개발 환경에 FFmpeg가 없으면 DB 테스트(conftest.py)처럼 통합 테스트만 skip한다."""
    try:
        return resolve_ffmpeg_binary()
    except RenderExecutionError as exc:
        pytest.skip(f"FFmpeg가 설치되어 있지 않아 FFmpeg 실행 테스트를 건너뜁니다: {exc}")


def test_render_video_handler_registered():
    assert JobType.RENDER_VIDEO in HANDLERS
    assert HANDLERS[JobType.RENDER_VIDEO] is handle_render_video


def test_confidence_style_prompts_match_e2_prompt_builder():
    assert set(CONFIDENCE_STYLE_PROMPTS) == {Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW}
    for level in Confidence:
        style = confidence_style_for(level.value)
        assert style
        built = build_prompt("A dark school hallway", confidence_style=style)
        assert f"Memory clarity: {style}." in built


def test_build_filter_complex_without_ffmpeg_binary(tmp_path: Path):
    nar = tmp_path / "nar.mp3"
    nar.write_bytes(b"fake-mp3")
    settings = RenderSettings(width=1280, height=720, fps=30, default_scene_duration=4.0, transition_duration=0.5)
    filter_str, has_audio = _build_filter_complex(
        scene_durations=[4.0, 5.2, 4.0],
        start_offsets=[0.0, 3.5, 8.2],
        total_duration=12.2,
        valid_narrations=[None, nar, None],
        settings=settings,
    )
    assert has_audio is True
    assert "scale=2560:1440:force_original_aspect_ratio=decrease" in filter_str
    assert "pad=2560:1440" in filter_str
    assert "zoompan=" in filter_str
    assert "xfade=transition=fade:duration=0.500:offset=3.500" in filter_str
    assert "adelay=3500|3500" in filter_str
    assert "amix=inputs=2" in filter_str


def test_compose_and_verify_with_mocked_ffmpeg(tmp_path: Path, monkeypatch):
    from worker.render import video as video_mod

    img1 = _make_checker_image(tmp_path / "s1.png", size=(640, 360))
    img2 = _make_checker_image(tmp_path / "s2.png", size=(640, 360))
    out_mp4 = tmp_path / "mocked.mp4"

    recorded_cmds: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        recorded_cmds.append(list(cmd))
        # 합성 호출이면 가짜 MP4 파일 생성, 검증 호출이면 스트림 헤더 stderr 반환
        if "-frames:v" in cmd:
            stderr = (
                "  Duration: 00:00:07.50, start: 0.000000, bitrate: 400 kb/s\n"
                "  Stream #0:0(und): Video: h264 (High), yuv420p, 1280x720, 30 fps\n"
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=stderr)
        Path(cmd[-1]).write_bytes(b"fake-mp4-stream")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(video_mod, "resolve_ffmpeg_binary", lambda: "/mock/ffmpeg")
    monkeypatch.setattr(video_mod.subprocess, "run", fake_run)

    comp = compose_slideshow_video(
        [
            SceneRenderInput(order=1, scene_id=1, version_no=1, image_path=img1),
            SceneRenderInput(order=2, scene_id=2, version_no=1, image_path=img2),
        ],
        out_mp4,
    )
    assert comp.width == 1280 and comp.height == 720
    assert comp.duration == pytest.approx(7.5)
    assert recorded_cmds[0][0] == "/mock/ffmpeg"

    def fake_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["/mock/ffmpeg"], timeout=1.0)

    monkeypatch.setattr(video_mod.subprocess, "run", fake_timeout)
    with pytest.raises(RenderTimeoutError):
        compose_slideshow_video(
            [SceneRenderInput(order=1, scene_id=1, version_no=1, image_path=img1)],
            tmp_path / "timeout.mp4",
        )


def test_calculate_scene_timeline_with_overlap():
    scenes = [
        SceneRenderInput(scene_id=1, version_no=1, image_path=Path("a.png"), order=1),
        SceneRenderInput(scene_id=2, version_no=1, image_path=Path("b.png"), order=2),
        SceneRenderInput(scene_id=3, version_no=1, image_path=Path("c.png"), order=3),
    ]
    settings = RenderSettings(default_scene_duration=4.0, transition_duration=0.5)
    durations, offsets, total, _ = calculate_scene_timeline(scenes, settings)
    assert durations == [4.0, 4.0, 4.0]
    assert offsets == [0.0, 3.5, 7.0]
    assert total == pytest.approx(11.0)


def test_handle_render_video_end_to_end_and_retry_reuse(tmp_path: Path):
    _require_ffmpeg()
    ctx = FakeJobContext(storage_root=tmp_path, dream_id=7, job_id=101)

    # 정사각형(512x512) 및 와이드(640x360) 이미지를 섞어 여백(pad) 처리도 함께 검증
    for scene_id, size in [(1, (512, 512)), (2, (640, 360)), (3, (512, 512))]:
        orig_path = ctx.path_for("scene_original", scene_id=scene_id, version_no=1)
        _make_checker_image(orig_path, size=size)

    payload = {
        "render_id": 55,
        "elements": [
            {"type": "place", "name": "학교 복도", "confidence": "low"},
            {"type": "person", "name": "할머니", "confidence": "high"},
            {"type": "object", "name": "우산", "confidence": "high"},
            {"type": "place", "name": "바다", "confidence": "medium"},
            {"type": "emotion", "name": "두려움", "confidence": "high"},
        ],
        "scenes": [
            {
                "order": 1,
                "scene_id": 1,
                "version_no": 1,
                "scene_version_id": 1001,
                "element_names": ["학교 복도", "두려움"],
            },
            {
                "order": 2,
                "scene_id": 2,
                "version_no": 1,
                "scene_version_id": 1002,
                "element_names": ["학교 복도", "할머니", "우산"],
            },
            {
                "order": 3,
                "scene_id": 3,
                "version_no": 1,
                "scene_version_id": 1003,
                "element_names": ["바다", "우산", "두려움"],
            },
        ],
        "render_settings": {
            "width": 1280,
            "height": 720,
            "fps": 30,
            "default_scene_duration": 1.2,
            "transition_duration": 0.3,
            "preset": "ultrafast",
        },
    }

    result = handle_render_video(ctx, payload)

    # 4단계 진행 보고 순서 확인
    assert ctx.stages == [
        JobStage.VALIDATING_INPUT,
        JobStage.POSTPROCESSING,
        JobStage.COMPOSING,
        JobStage.VERIFYING,
    ]

    assert result["render_id"] == 55
    assert result["video_path"] == "dreams/7/renders/55/video.mp4"
    assert result["video_url"] == "/storage/dreams/7/renders/55/video.mp4"
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["scene_version_ids"] == [1001, 1002, 1003]
    # 1.2s * 3 - 0.3s * 2 = 3.0s
    assert result["duration"] == pytest.approx(3.0, abs=0.4)

    levels = [s["confidence_level"] for s in result["scenes"]]
    assert levels == ["low", "medium", "high"]
    assert all(not s["reused_existing_blur"] for s in result["scenes"])

    final_video = tmp_path / result["video_path"]
    assert final_video.is_file()

    # 재시도 호출 시 이미 저장된 후처리 이미지를 재사용하는지 확인
    ctx_retry = FakeJobContext(storage_root=tmp_path, dream_id=7, job_id=102)
    retry_result = handle_render_video(ctx_retry, payload)
    assert all(s["reused_existing_blur"] for s in retry_result["scenes"])


def test_compose_with_narration_extends_duration_and_adds_audio(tmp_path: Path):
    ffmpeg_exe = _require_ffmpeg()
    img1 = _make_checker_image(tmp_path / "s1.png", size=(640, 360))
    img2 = _make_checker_image(tmp_path / "s2.png", size=(640, 360))

    # 2.0초 길이의 테스트 나레이션 오디오 생성
    nar1 = tmp_path / "nar1.mp3"
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.0",
            str(nar1),
        ],
        check=True,
    )

    settings = RenderSettings(
        width=640,
        height=360,
        fps=30,
        default_scene_duration=1.2,
        transition_duration=0.3,
        narration_padding=0.3,
        preset="ultrafast",
    )
    scenes = [
        SceneRenderInput(order=1, scene_id=1, version_no=1, image_path=img1, narration_path=nar1),
        SceneRenderInput(order=2, scene_id=2, version_no=1, image_path=img2),
    ]
    out_video = tmp_path / "with_narration.mp4"
    comp = compose_slideshow_video(scenes, out_video, settings=settings)

    # 장면 1은 기본 1.2s 대신 나레이션(2.0s) + 여유(0.3s) + 전환(0.3s) = 2.6s로 늘어나야 함
    assert comp.scene_durations[0] >= 2.5
    assert comp.has_audio is True


def test_handle_render_video_fails_when_image_missing(tmp_path: Path):
    ctx = FakeJobContext(storage_root=tmp_path, dream_id=1, job_id=1)
    payload = {
        "render_id": 1,
        "scenes": [
            {"order": 1, "scene_id": 1, "version_no": 1, "confidence_level": "high"},
        ],
    }
    with pytest.raises(JobError) as exc_info:
        handle_render_video(ctx, payload)
    assert exc_info.value.code == FailureCode.INVALID_INPUT


def test_verify_rendered_video_rejects_wrong_resolution(tmp_path: Path):
    _require_ffmpeg()
    img = _make_checker_image(tmp_path / "s1.png", size=(640, 360))
    out_video = tmp_path / "small.mp4"
    compose_slideshow_video(
        [SceneRenderInput(order=1, scene_id=1, version_no=1, image_path=img)],
        out_video,
        settings=RenderSettings(width=640, height=360, default_scene_duration=1.0, transition_duration=0.2, preset="ultrafast"),
    )
    with pytest.raises(RenderExecutionError, match="해상도"):
        verify_rendered_video(out_video, expected_width=1280, expected_height=720)


def test_local_pipeline_script_runs_end_to_end(monkeypatch, tmp_path):
    """scripts/e1_local_pipeline.py: OpenAI 목업 이미지 → 블러 → 영상까지 tmp 저장소에서 끝까지 돈다."""
    _require_ffmpeg()
    import scripts.e1_local_pipeline as pipeline
    import worker.image_gen.generate as image_gen
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_path", tmp_path)  # cached_property라 값을 직접 바꾼다
    monkeypatch.setattr(image_gen, "get_client", image_gen.get_client)  # 스크립트가 바꾼 것을 테스트 후 되돌림
    monkeypatch.setattr("sys.argv", ["e1_local_pipeline.py"])

    assert pipeline.main() == 0
    assert (tmp_path / "dreams/1/renders/1/video.mp4").stat().st_size > 0
    assert (tmp_path / "dreams/1/scenes/3/v1/blur_medium.png").is_file()
