"""FFmpeg 기반 슬라이드 영상 합성 및 검증 모듈 (E1 담당).

규칙 (계획서 3.3, 3.4, 3.5):
- 후처리가 끝난 장면 이미지를 순서대로 연결하여 슬라이드 영상을 생성한다.
- 정지 이미지에 천천히 확대·이동하는 Ken Burns 효과(`zoompan`)를 적용하고,
  장면 사이에는 부드러운 전환(`xfade`)을 넣는다.
- 이미지 비율이 영상 규격(기본 1280×720)과 다르면 여백(`pad`)을 추가해 주요 내용이 잘리지 않도록 한다.
- 기본 출력 규격: 1280×720, 30fps, MP4(H.264 / yuv420p).
- 나레이션이 없으면 장면당 기본 4.0초를 사용하며, 전체 재생 길이는 장면 전환이 겹치는 시간을 반영해 계산한다:
    total_duration = sum(scene_durations) - (N - 1) * transition_duration
- 선택 기능으로 장면별 나레이션 음성이 제공되면 음성 길이 + 여유 시간 + 전환 시간만큼 장면 길이를 늘려
  말이 끝나기 전에 장면이 바뀌지 않도록 한다.
- 렌더링 완료 후 출력 파일의 존재, 재생 가능 여부, 해상도, 재생 길이를 검증한다.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RenderInputError(ValueError):
    """렌더링 입력(장면 목록, 이미지 경로, 설정값 등)이 잘못되었을 때 발생하는 예외."""


class RenderExecutionError(RuntimeError):
    """FFmpeg 실행 실패 또는 출력 영상 검증 실패 시 발생하는 예외."""


class RenderTimeoutError(TimeoutError):
    """FFmpeg 렌더링이 제한 시간을 초과했을 때 발생하는 예외."""


@dataclass(frozen=True)
class RenderSettings:
    """FFmpeg 슬라이드 영상 렌더링 규격 설정."""

    width: int = 1280
    height: int = 720
    fps: int = 30
    default_scene_duration: float = 4.0
    transition_duration: float = 0.5
    transition_type: str = "fade"
    max_zoom: float = 1.08
    narration_padding: float = 0.4
    crf: int = 20
    preset: str = "medium"
    duration_tolerance: float = 0.6

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("영상 가로·세로 해상도는 양수여야 합니다.")
        if self.width % 2 != 0 or self.height % 2 != 0:
            raise ValueError("H.264(yuv420p) 인코딩을 위해 가로·세로 해상도는 짝수여야 합니다.")
        if self.fps <= 0:
            raise ValueError("fps는 양수여야 합니다.")
        if self.default_scene_duration <= 0:
            raise ValueError("default_scene_duration은 양수여야 합니다.")
        if self.transition_duration < 0:
            raise ValueError("transition_duration은 0 이상이어야 합니다.")
        if self.transition_duration >= self.default_scene_duration:
            raise ValueError("transition_duration은 default_scene_duration보다 작아야 합니다.")
        if not (1.0 <= self.max_zoom <= 1.25):
            raise ValueError("max_zoom은 1.0 이상 1.25 이하여야 합니다.")

    def to_metadata(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "default_scene_duration": self.default_scene_duration,
            "transition_duration": self.transition_duration,
            "transition_type": self.transition_type,
            "max_zoom": self.max_zoom,
            "narration_padding": self.narration_padding,
        }


DEFAULT_RENDER_SETTINGS = RenderSettings()


@dataclass(frozen=True)
class SceneRenderInput:
    """렌더링에 투입할 개별 장면 입력."""

    scene_id: int
    version_no: int
    image_path: Path
    order: int = 1
    duration: float | None = None
    narration_path: Path | None = None
    narration_duration: float | None = None


@dataclass(frozen=True)
class VideoVerificationResult:
    """렌더링 결과 영상 검증 정보."""

    video_path: str
    file_size_bytes: int
    width: int
    height: int
    fps: float
    duration: float
    expected_duration: float
    codec: str
    has_audio: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_path": self.video_path,
            "file_size_bytes": self.file_size_bytes,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration": self.duration,
            "expected_duration": self.expected_duration,
            "codec": self.codec,
            "has_audio": self.has_audio,
        }


@dataclass(frozen=True)
class RenderCompositionResult:
    """슬라이드 영상 합성 및 검증 완료 결과."""

    output_path: str
    width: int
    height: int
    fps: float
    duration: float
    expected_duration: float
    scene_durations: tuple[float, ...]
    scene_start_offsets: tuple[float, ...]
    has_audio: bool
    verification: VideoVerificationResult


def resolve_ffmpeg_binary() -> str:
    """실행 가능한 FFmpeg 바이너리 경로를 찾는다.

    우선순위:
    1. 환경변수 `FFMPEG_BIN`
    2. 시스템 PATH의 `ffmpeg` (Docker 컨테이너 포함)
    3. `imageio_ffmpeg.get_ffmpeg_exe()` (로컬 개발 환경 폴백)
    """
    env_bin = os.getenv("FFMPEG_BIN")
    if env_bin and Path(env_bin).is_file():
        return env_bin

    sys_bin = shutil.which("ffmpeg")
    if sys_bin:
        return sys_bin

    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return str(exe)
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("imageio_ffmpeg 폴백 확인 실패: %s", exc)

    raise RenderExecutionError("FFmpeg 실행 파일을 찾을 수 없습니다. ffmpeg 설치 여부를 확인해 주세요.")


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_STREAM_RE = re.compile(
    r"Stream\s+#\d+:\d+.*?Video:\s*([a-zA-Z0-9_]+).*?,\s*(\d+)x(\d+)(?:[\s,\[].*?)?(?:,\s*(\d+(?:\.\d+)?)\s*fps)?"
)
_AUDIO_STREAM_RE = re.compile(r"Stream\s+#\d+:\d+.*?Audio:\s*([a-zA-Z0-9_]+)")


def _parse_duration_seconds(stderr_text: str) -> float | None:
    match = _DURATION_RE.search(stderr_text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return round(hours * 3600 + minutes * 60 + seconds, 3)


def probe_media_duration(
    media_path: Path | str,
    *,
    ffmpeg_bin: str | None = None,
    timeout: float = 15.0,
) -> float | None:
    """미디어(음성/영상) 파일의 재생 길이(초)를 FFmpeg 헤더에서 추출한다."""
    path = Path(media_path)
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return None

    exe = ffmpeg_bin or resolve_ffmpeg_binary()
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None

    return _parse_duration_seconds(proc.stderr or "")


def calculate_scene_timeline(
    scenes: Sequence[SceneRenderInput],
    settings: RenderSettings = DEFAULT_RENDER_SETTINGS,
    *,
    ffmpeg_bin: str | None = None,
) -> tuple[list[float], list[float], float, list[Path | None]]:
    """장면별 재생 길이, 시작 오프셋, 전체 재생 길이, 유효한 나레이션 경로 목록을 계산한다.

    나레이션이 있는 장면은 말이 끝나기 전에 장면 전환이 시작되지 않도록
    `audio_duration + narration_padding + transition_overlap` 이상으로 장면 길이를 확보한다.
    """
    if not scenes:
        raise RenderInputError("렌더링할 장면이 없습니다.")

    n_scenes = len(scenes)
    t_fade = settings.transition_duration if n_scenes > 1 else 0.0

    scene_durations: list[float] = []
    valid_narrations: list[Path | None] = []

    for idx, scene in enumerate(scenes):
        base_dur = (
            float(scene.duration)
            if scene.duration is not None and scene.duration > 0
            else settings.default_scene_duration
        )
        narration_file: Path | None = None
        audio_dur: float | None = None

        if scene.narration_path is not None:
            candidate = Path(scene.narration_path)
            if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
                probed = (
                    float(scene.narration_duration)
                    if scene.narration_duration is not None and scene.narration_duration > 0
                    else probe_media_duration(candidate, ffmpeg_bin=ffmpeg_bin)
                )
                if probed is not None and probed > 0:
                    narration_file = candidate
                    audio_dur = probed
                else:
                    logger.warning(
                        "장면 %s 나레이션 파일 길이를 확인할 수 없어 나레이션 없이 진행합니다: %s",
                        scene.scene_id,
                        candidate,
                    )
            else:
                logger.warning(
                    "장면 %s 나레이션 파일이 존재하지 않아 나레이션 없이 진행합니다: %s",
                    scene.scene_id,
                    candidate,
                )

        if audio_dur is not None:
            # 다음 장면과 겹치는 전환 시간 전에 나레이션이 끝나도록 여유 시간 확보
            trailing_overlap = t_fade if idx < n_scenes - 1 else 0.0
            required_dur = audio_dur + settings.narration_padding + trailing_overlap
            dur = max(base_dur, round(required_dur, 2))
        else:
            dur = base_dur

        if dur <= t_fade:
            raise RenderInputError(
                f"장면 {scene.scene_id} 재생 길이({dur}s)가 장면 전환 시간({t_fade}s)보다 짧거나 같습니다."
            )

        scene_durations.append(round(dur, 3))
        valid_narrations.append(narration_file)

    start_offsets: list[float] = []
    elapsed = 0.0
    for idx, dur in enumerate(scene_durations):
        start_offsets.append(round(elapsed, 3))
        elapsed += dur - (t_fade if idx < n_scenes - 1 else 0.0)

    total_duration = round(sum(scene_durations) - max(0, n_scenes - 1) * t_fade, 3)
    return scene_durations, start_offsets, total_duration, valid_narrations


def _build_ken_burns_expr(
    scene_index: int,
    frames: int,
    max_zoom: float,
) -> tuple[str, str, str]:
    """장면 인덱스에 따라 자연스러운 Ken Burns 확대·이동 수식을 생성한다.

    모든 수식은 1.0 <= zoom <= max_zoom 범위 안에서만 동작하며,
    가장자리가 노출되거나 주요 인물이 과도하게 잘리지 않는다.
    """
    safe_frames = max(frames, 2)
    zoom_span = max(0.0, max_zoom - 1.0)
    step = round(zoom_span / safe_frames, 6)

    mode = scene_index % 3
    if mode == 0:
        # 중심부 완만한 확대 (Zoom-in)
        z_expr = f"min(zoom+{step:.6f},{max_zoom:.4f})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif mode == 1:
        # 완만한 축소 (Zoom-out: max_zoom -> 1.0)
        z_expr = f"if(eq(on,1),{max_zoom:.4f},max(zoom-{step:.6f},1.0))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        # 완만한 수평 패닝 + 미세 확대
        mid_zoom = round(1.0 + zoom_span * 0.65, 4)
        z_expr = f"{mid_zoom:.4f}"
        x_expr = f"(iw-iw/zoom)*(0.35+0.30*on/{safe_frames})"
        y_expr = "ih/2-(ih/zoom/2)"

    return z_expr, x_expr, y_expr


def _build_filter_complex(
    scene_durations: Sequence[float],
    start_offsets: Sequence[float],
    total_duration: float,
    valid_narrations: Sequence[Path | None],
    settings: RenderSettings,
) -> tuple[str, bool]:
    """FFmpeg `-filter_complex` 그래프 문자열과 오디오 트랙 포함 여부를 생성한다."""
    w = settings.width
    h = settings.height
    super_w = w * 2
    super_h = h * 2
    fps = settings.fps
    t_fade = settings.transition_duration

    parts: list[str] = []

    for idx, dur in enumerate(scene_durations):
        frames = max(2, round(dur * fps))
        z_expr, x_expr, y_expr = _build_ken_burns_expr(idx, frames, settings.max_zoom)
        chain = (
            f"[{idx}:v]"
            f"scale={super_w}:{super_h}:force_original_aspect_ratio=decrease,"
            f"pad={super_w}:{super_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,"
            f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={w}x{h}:fps={fps},"
            f"trim=duration={dur:.3f},setpts=PTS-STARTPTS,"
            f"format=yuv420p,settb=AVTB"
            f"[v{idx}]"
        )
        parts.append(chain)

    n_scenes = len(scene_durations)
    if n_scenes == 1:
        parts.append("[v0]null[vout]")
    else:
        prev_label = "v0"
        for idx in range(1, n_scenes):
            offset = start_offsets[idx]
            out_label = "vout" if idx == n_scenes - 1 else f"vx{idx}"
            parts.append(
                f"[{prev_label}][v{idx}]"
                f"xfade=transition={settings.transition_type}:"
                f"duration={t_fade:.3f}:offset={offset:.3f}"
                f"[{out_label}]"
            )
            prev_label = out_label

    # 선택 기능: 장면별 나레이션 오디오 트랙 결합
    audio_inputs: list[tuple[int, int, float]] = []
    next_input_idx = n_scenes
    for scene_idx, nar_path in enumerate(valid_narrations):
        if nar_path is not None:
            audio_inputs.append((scene_idx, next_input_idx, start_offsets[scene_idx]))
            next_input_idx += 1

    has_audio = len(audio_inputs) > 0
    if has_audio:
        parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate=44100,"
            f"atrim=duration={total_duration:.3f},asetpts=PTS-STARTPTS[abase]"
        )
        mix_labels = ["[abase]"]
        for scene_idx, input_idx, offset_sec in audio_inputs:
            delay_ms = max(0, round(offset_sec * 1000))
            lbl = f"aud{scene_idx}"
            parts.append(
                f"[{input_idx}:a]"
                f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                f"adelay={delay_ms}|{delay_ms}"
                f"[{lbl}]"
            )
            mix_labels.append(f"[{lbl}]")

        num_mix = len(mix_labels)
        parts.append(
            f"{''.join(mix_labels)}"
            f"amix=inputs={num_mix}:duration=first:dropout_transition=0:normalize=0,"
            f"atrim=duration={total_duration:.3f},asetpts=PTS-STARTPTS[aout]"
        )

    return ";".join(parts), has_audio


def verify_rendered_video(
    video_path: Path | str,
    *,
    expected_width: int = 1280,
    expected_height: int = 720,
    expected_duration: float | None = None,
    duration_tolerance: float = 0.6,
    ffmpeg_bin: str | None = None,
    timeout: float = 30.0,
) -> VideoVerificationResult:
    """생성된 MP4 영상의 존재, 크기, 스트림 디코딩 가능 여부, 해상도, 재생 길이를 검증한다."""
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        raise RenderExecutionError(f"렌더링 출력 영상 파일이 존재하지 않습니다: {path}")

    file_size = path.stat().st_size
    if file_size <= 0:
        raise RenderExecutionError(f"렌더링 출력 영상 파일이 비어 있습니다: {path}")

    exe = ffmpeg_bin or resolve_ffmpeg_binary()

    # 1. 스트림 메타데이터 확인 및 첫 프레임 실제 디코딩 검사
    try:
        proc = subprocess.run(
            [
                exe,
                "-hide_banner",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderTimeoutError(f"출력 영상 검증 중 시간이 초과되었습니다: {path}") from exc
    except OSError as exc:
        raise RenderExecutionError(f"FFmpeg 검증 실행에 실패했습니다: {exc}") from exc

    stderr_text = proc.stderr or ""
    if proc.returncode != 0:
        raise RenderExecutionError(
            f"렌더링된 영상을 디코딩할 수 없습니다 ( 손상된 파일 ): {stderr_text[-400:]}"
        )

    v_match = _VIDEO_STREAM_RE.search(stderr_text)
    if not v_match:
        raise RenderExecutionError(f"출력 파일에서 비디오 스트림을 찾을 수 없습니다: {path}")

    codec = v_match.group(1)
    width = int(v_match.group(2))
    height = int(v_match.group(3))
    fps = float(v_match.group(4)) if v_match.group(4) else 30.0

    if width != expected_width or height != expected_height:
        raise RenderExecutionError(
            f"출력 영상 해상도({width}x{height})가 목표 규격({expected_width}x{expected_height})과 다릅니다."
        )

    duration = _parse_duration_seconds(stderr_text)
    if duration is None or duration <= 0:
        raise RenderExecutionError(f"출력 영상의 재생 길이를 확인할 수 없습니다: {path}")

    target_dur = expected_duration if expected_duration is not None else duration
    if expected_duration is not None and abs(duration - expected_duration) > duration_tolerance:
        raise RenderExecutionError(
            f"출력 영상 재생 길이({duration:.2f}s)가 예상 길이({expected_duration:.2f}s)와 "
            f"허용 오차({duration_tolerance:.2f}s) 이상 차이납니다."
        )

    has_audio = _AUDIO_STREAM_RE.search(stderr_text) is not None

    return VideoVerificationResult(
        video_path=str(path),
        file_size_bytes=file_size,
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        expected_duration=round(target_dur, 3),
        codec=codec,
        has_audio=has_audio,
    )


def compose_slideshow_video(
    scenes: Sequence[SceneRenderInput],
    output_path: Path | str,
    settings: RenderSettings | None = None,
    *,
    timeout: float = 300.0,
    ffmpeg_bin: str | None = None,
) -> RenderCompositionResult:
    """후처리된 장면 이미지들을 받아 Ken Burns 효과와 장면 전환이 적용된 MP4 영상을 합성하고 검증한다."""
    cfg = settings or DEFAULT_RENDER_SETTINGS
    if not scenes:
        raise RenderInputError("합성할 장면 목록이 비어 있습니다.")

    ordered_scenes = sorted(scenes, key=lambda s: s.order)
    for scene in ordered_scenes:
        img_path = Path(scene.image_path)
        if not img_path.exists() or not img_path.is_file() or img_path.stat().st_size == 0:
            raise RenderInputError(
                f"장면 {scene.scene_id}(v{scene.version_no}) 이미지 파일이 없거나 비어 있습니다: {img_path}"
            )

    exe = ffmpeg_bin or resolve_ffmpeg_binary()
    scene_durations, start_offsets, total_duration, valid_narrations = calculate_scene_timeline(
        ordered_scenes,
        cfg,
        ffmpeg_bin=exe,
    )

    filter_complex, has_audio = _build_filter_complex(
        scene_durations=scene_durations,
        start_offsets=start_offsets,
        total_duration=total_duration,
        valid_narrations=valid_narrations,
        settings=cfg,
    )

    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [exe, "-y", "-hide_banner", "-loglevel", "error"]
    for scene in ordered_scenes:
        cmd.extend(["-i", str(scene.image_path)])
    for nar_path in valid_narrations:
        if nar_path is not None:
            cmd.extend(["-i", str(nar_path)])

    cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]"])
    if has_audio:
        cmd.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"])
    else:
        cmd.append("-an")

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            cfg.preset,
            "-crf",
            str(cfg.crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(cfg.fps),
            "-movflags",
            "+faststart",
            str(dst),
        ]
    )

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderTimeoutError(
            f"FFmpeg 영상 합성 시간이 제한 시간({timeout}초)을 초과했습니다."
        ) from exc
    except OSError as exc:
        raise RenderExecutionError(f"FFmpeg 프로세스 실행 실패: {exc}") from exc

    if proc.returncode != 0:
        err_msg = (proc.stderr or "").strip()
        raise RenderExecutionError(
            f"FFmpeg 영상 합성에 실패했습니다 (exit={proc.returncode}): {err_msg[-500:]}"
        )

    verification = verify_rendered_video(
        dst,
        expected_width=cfg.width,
        expected_height=cfg.height,
        expected_duration=total_duration,
        duration_tolerance=cfg.duration_tolerance,
        ffmpeg_bin=exe,
    )

    return RenderCompositionResult(
        output_path=str(dst),
        width=verification.width,
        height=verification.height,
        fps=verification.fps,
        duration=verification.duration,
        expected_duration=total_duration,
        scene_durations=tuple(scene_durations),
        scene_start_offsets=tuple(start_offsets),
        has_audio=verification.has_audio,
        verification=verification,
    )
