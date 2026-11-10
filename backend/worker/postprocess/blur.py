"""Pillow Gaussian Blur 기반 확신도 이미지 후처리 모듈 (E1 담당).

규칙 (계획서 3.2 및 파일 경로 규칙):
- 확실(high) 단계는 블러 없이 원본 선명도를 유지하고,
  보통(medium)과 흐릿(low) 단계는 각각 약한 블러와 강한 블러를 적용한다.
- 해상도 차이로 블러 체감 강도가 달라지는 문제를 줄이기 위해 기준 해상도(기본 긴 변 1280px)
  대비 반경 보정 옵션을 제공한다.
- 원본 이미지(`original.png`)는 절대 덮어쓰지 않고, 후처리 결과는 `blur_{level}.png`로 별도 저장한다.
- 수동 재시도 시 이미 검증된 후처리 이미지가 있으면 재사용할 수 있다(`reuse_existing=True`).
- 결과에는 장면 버전, 확신도 단계, 블러 강도, 처리 규격 설정을 함께 기록한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from app.core.enums import Confidence
from app.storage import paths as storage_paths
from worker.postprocess.confidence import RULE_VERSION, parse_confidence


class PostprocessImageError(ValueError):
    """원본 이미지가 없거나 손상되었을 때, 또는 잘못된 후처리 요청일 때 발생하는 예외."""


@dataclass(frozen=True)
class BlurSettings:
    """단계별 Gaussian Blur 반경 및 처리 규격 설정."""

    high_radius: float = 0.0
    medium_radius: float = 6.0
    low_radius: float = 16.0
    reference_long_edge: int = 1280
    normalize_by_resolution: bool = True
    target_size: tuple[int, int] | None = None
    pad_color: tuple[int, int, int] = (0, 0, 0)
    output_format: str = "PNG"

    def __post_init__(self) -> None:
        if self.high_radius < 0 or self.medium_radius < 0 or self.low_radius < 0:
            raise ValueError("블러 반경(radius)은 0 이상이어야 합니다.")
        if not (self.high_radius <= self.medium_radius <= self.low_radius):
            raise ValueError("블러 반경은 high <= medium <= low 순서여야 합니다.")
        if self.reference_long_edge <= 0:
            raise ValueError("reference_long_edge는 양수여야 합니다.")
        if self.target_size is not None:
            w, h = self.target_size
            if w <= 0 or h <= 0:
                raise ValueError("target_size의 가로·세로 크기는 양수여야 합니다.")

    def base_radius_for(self, level: Confidence | str) -> float:
        """확신도 단계별 기본 블러 반경(radius)을 반환한다."""
        parsed = parse_confidence(level)
        if parsed == Confidence.HIGH:
            return float(self.high_radius)
        if parsed == Confidence.MEDIUM:
            return float(self.medium_radius)
        return float(self.low_radius)

    def effective_radius_for(
        self,
        level: Confidence | str,
        width: int,
        height: int,
    ) -> float:
        """이미지 해상도를 반영한 실제 적용 블러 반경(radius)을 계산한다."""
        base = self.base_radius_for(level)
        if base <= 0.0 or not self.normalize_by_resolution:
            return round(base, 4)
        long_edge = max(width, height)
        if long_edge <= 0:
            return round(base, 4)
        scale = long_edge / float(self.reference_long_edge)
        return round(base * scale, 4)

    def to_metadata(self) -> dict[str, Any]:
        """DB(`renders.postprocess_settings`) 및 결과 기록용 설정 딕셔너리."""
        return {
            "aggregation_rule": RULE_VERSION,
            "radius_by_level": {
                Confidence.HIGH.value: self.high_radius,
                Confidence.MEDIUM.value: self.medium_radius,
                Confidence.LOW.value: self.low_radius,
            },
            "reference_long_edge": self.reference_long_edge,
            "normalize_by_resolution": self.normalize_by_resolution,
            "target_size": list(self.target_size) if self.target_size else None,
            "output_format": self.output_format,
        }


DEFAULT_BLUR_SETTINGS = BlurSettings()


@dataclass(frozen=True)
class PostprocessResult:
    """장면 1건의 블러 후처리 결과 및 메타데이터."""

    scene_id: int | None
    version_no: int | None
    confidence_level: Confidence
    base_radius: float
    blur_radius: float
    source_path: str
    output_path: str
    width: int
    height: int
    reused_existing: bool
    settings: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "version_no": self.version_no,
            "confidence_level": self.confidence_level.value,
            "base_radius": self.base_radius,
            "blur_radius": self.blur_radius,
            "source_path": self.source_path,
            "output_path": self.output_path,
            "width": self.width,
            "height": self.height,
            "reused_existing": self.reused_existing,
            "settings": self.settings,
        }


def _load_rgb_image(path: Path) -> Image.Image:
    if not path.exists() or not path.is_file():
        raise PostprocessImageError(f"원본 이미지 파일이 존재하지 않습니다: {path}")
    if path.stat().st_size == 0:
        raise PostprocessImageError(f"원본 이미지 파일이 비어 있습니다: {path}")
    try:
        with Image.open(path) as img:
            img.load()
            if img.width <= 0 or img.height <= 0:
                raise PostprocessImageError(f"유효하지 않은 이미지 크기입니다: {img.size}")
            return img.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise PostprocessImageError(f"이미지를 읽을 수 없거나 손상되었습니다 ({path}): {exc}") from exc


def _try_inspect_existing(path: Path) -> tuple[int, int] | None:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        with Image.open(path) as img:
            img.load()
            if img.width > 0 and img.height > 0:
                return img.width, img.height
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return None


def apply_confidence_blur(
    source_path: Path | str,
    output_path: Path | str,
    confidence_level: Confidence | str,
    settings: BlurSettings | None = None,
    *,
    scene_id: int | None = None,
    version_no: int | None = None,
    reuse_existing: bool = False,
) -> PostprocessResult:
    """원본 이미지를 받아 확신도 단계에 맞는 Gaussian Blur를 적용하고 별도 경로에 저장한다.

    Args:
        source_path: 원본 이미지 경로 (`original.png`). 절대 덮어쓰지 않는다.
        output_path: 후처리 이미지 저장 경로 (`blur_{level}.png`).
        confidence_level: 장면 확신도 단계 (`high`, `medium`, `low`).
        settings: 블러 반경 및 규격 설정. 미지정 시 기본 설정 사용.
        scene_id: 기록용 장면 ID.
        version_no: 기록용 장면 버전 번호.
        reuse_existing: True이고 `output_path`에 정상 이미지가 이미 있으면 재계산 없이 재사용.

    Returns:
        PostprocessResult: 후처리 결과 메타데이터.
    """
    cfg = settings or DEFAULT_BLUR_SETTINGS
    level = parse_confidence(confidence_level)

    src = Path(source_path)
    dst = Path(output_path)

    if src.resolve() == dst.resolve():
        raise PostprocessImageError(
            f"원본 이미지를 덮어쓸 수 없습니다. source_path와 output_path가 같습니다: {src}"
        )

    # 원본 이미지 유효성 확인은 항상 수행 (원본 누락·손상 감지를 위해)
    image = _load_rgb_image(src)

    if reuse_existing:
        existing_size = _try_inspect_existing(dst)
        if existing_size is not None:
            w, h = existing_size
            base_r = cfg.base_radius_for(level)
            eff_r = cfg.effective_radius_for(level, w, h)
            return PostprocessResult(
                scene_id=scene_id,
                version_no=version_no,
                confidence_level=level,
                base_radius=base_r,
                blur_radius=eff_r,
                source_path=str(src),
                output_path=str(dst),
                width=w,
                height=h,
                reused_existing=True,
                settings=cfg.to_metadata(),
            )

    if cfg.target_size is not None and image.size != cfg.target_size:
        image = ImageOps.pad(
            image,
            cfg.target_size,
            method=Image.Resampling.LANCZOS,
            color=cfg.pad_color,
        )

    width, height = image.size
    base_radius = cfg.base_radius_for(level)
    effective_radius = cfg.effective_radius_for(level, width, height)

    if effective_radius > 0.0:
        processed = image.filter(ImageFilter.GaussianBlur(radius=effective_radius))
    else:
        processed = image.copy()

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.with_name(f".{dst.name}.tmp")
    try:
        processed.save(tmp_dst, format=cfg.output_format)
        tmp_dst.replace(dst)
    finally:
        if tmp_dst.exists():
            tmp_dst.unlink(missing_ok=True)

    return PostprocessResult(
        scene_id=scene_id,
        version_no=version_no,
        confidence_level=level,
        base_radius=base_radius,
        blur_radius=effective_radius,
        source_path=str(src),
        output_path=str(dst),
        width=width,
        height=height,
        reused_existing=False,
        settings=cfg.to_metadata(),
    )


def postprocess_scene_for_storage(
    storage_root: Path | str,
    dream_id: int,
    scene_id: int,
    version_no: int,
    confidence_level: Confidence | str,
    settings: BlurSettings | None = None,
    *,
    reuse_existing: bool = True,
) -> PostprocessResult:
    """파일 저장 경로 규칙(`app.storage.paths`)에 맞춰 장면 이미지를 블러 후처리한다."""
    root = Path(storage_root)
    level = parse_confidence(confidence_level)

    rel_src = storage_paths.scene_original(dream_id, scene_id, version_no)
    rel_dst = storage_paths.scene_blur(dream_id, scene_id, version_no, level.value)

    result = apply_confidence_blur(
        source_path=root / rel_src,
        output_path=root / rel_dst,
        confidence_level=level,
        settings=settings,
        scene_id=scene_id,
        version_no=version_no,
        reuse_existing=reuse_existing,
    )
    return PostprocessResult(
        scene_id=result.scene_id,
        version_no=result.version_no,
        confidence_level=result.confidence_level,
        base_radius=result.base_radius,
        blur_radius=result.blur_radius,
        source_path=str(rel_src),
        output_path=str(rel_dst),
        width=result.width,
        height=result.height,
        reused_existing=result.reused_existing,
        settings=result.settings,
    )
