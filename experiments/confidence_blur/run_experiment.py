"""E1 확신도 블러 후처리 및 FFmpeg 슬라이드 영상 렌더링 실험 스크립트.

실험 항목 (E1 개발계획서 3.1, 3.2, 3.3, 6절):
1. 장면 확신도 집계 규칙 검증 (시각 요소 평균, 감정 요소 제외, 경계값 0.5 / 1.5 확인)
2. 단계별 Gaussian Blur 강도 후보군(A: 약함, B: 기본, C: 강함) 비교 및 해상도 정규화 검증
3. 3개 장면(학교 복도 → 할머니와 노란 우산 → 창밖의 회색 바다) 후처리 및
   FFmpeg Ken Burns + Crossfade 슬라이드 영상(1280×720, 30fps, MP4) 합성·검증

실행 방법 (저장소 루트 또는 backend/ 기준):
    backend/.venv/bin/python experiments/confidence_blur/run_experiment.py
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.enums import Confidence
from worker.postprocess import (
    BlurSettings,
    aggregate_scene_confidence_detail,
    apply_confidence_blur,
)
from worker.render import (
    RenderSettings,
    SceneRenderInput,
    compose_slideshow_video,
)

EXPERIMENT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXPERIMENT_DIR / "outputs"
EXAMPLES_DIR = REPO_ROOT / "docs" / "schemas" / "examples"


def create_sample_scene_image(scene_order: int, size: tuple[int, int] = (1280, 720)) -> Image.Image:
    """팀 공통 예시(`docs/schemas/examples/scenes.json`)의 3개 장면을 시각적으로 구분 가능하게 생성한다.

    블러 강도별 인물·배경·사물 윤곽 식별도를 정량·정성 비교할 수 있도록
    배경 그라데이션, 건축/자연 구조선, 주요 인물·물건 실루엣, 세밀한 텍스처를 함께 배치한다.
    """
    w, h = size
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    if scene_order == 1:
        # 장면 1: 형광등이 깜빡이는 어두운 학교 복도 (place: 학교 복도, emotion: 두려움)
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(18 + 25 * t)
            g = int(24 + 34 * t)
            b = int(38 + 48 * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        # 원근 복도 벽면과 바닥 타일 격자
        vx, vy = w // 2, int(h * 0.42)
        draw.polygon([(0, 0), (w, 0), (int(w * 0.68), int(h * 0.25)), (int(w * 0.32), int(h * 0.25))], fill=(32, 42, 60))
        draw.polygon([(0, h), (w, h), (int(w * 0.68), int(h * 0.72)), (int(w * 0.32), int(h * 0.72))], fill=(28, 34, 46))
        draw.rectangle([int(w * 0.32), int(h * 0.25), int(w * 0.68), int(h * 0.72)], fill=(14, 18, 28), outline=(90, 110, 140), width=3)

        for offset in (-0.38, -0.22, -0.10, 0.10, 0.22, 0.38):
            draw.line([(vx, vy), (int(w * (0.5 + offset)), h)], fill=(65, 80, 105), width=2)

        # 좌우 교실 창문과 문 디테일
        for i in range(4):
            depth = (i + 1) / 5.0
            lx = int(w * (0.06 + 0.22 * depth))
            rx = int(w * (0.94 - 0.22 * depth))
            top_y = int(h * (0.18 + 0.10 * depth))
            bot_y = int(h * (0.82 - 0.10 * depth))
            draw.rectangle([lx, top_y, lx + int(w * 0.035), bot_y], outline=(110, 135, 165), width=2)
            draw.rectangle([rx - int(w * 0.035), top_y, rx, bot_y], outline=(110, 135, 165), width=2)

        # 천장 깜빡이는 형광등
        for tube_y, brightness in [(int(h * 0.08), 245), (int(h * 0.16), 180), (int(h * 0.22), 230)]:
            half_len = int(w * 0.12 * (1.0 - tube_y / h))
            draw.rectangle(
                [vx - half_len, tube_y - 4, vx + half_len, tube_y + 4],
                fill=(brightness, brightness, min(255, brightness + 10)),
                outline=(180, 210, 255),
                width=2,
            )

    elif scene_order == 2:
        # 장면 2: 분홍색 카디건을 입은 할머니가 노란 우산을 건네는 장면
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(42 + 45 * (1 - t))
            g = int(36 + 32 * (1 - t))
            b = int(52 + 28 * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        # 따뜻한 후광 조명
        cx, cy = int(w * 0.48), int(h * 0.48)
        for rad in range(int(h * 0.42), 10, -18):
            ratio = 1.0 - rad / (h * 0.42)
            c = (
                min(255, int(65 + 95 * ratio)),
                min(255, int(55 + 75 * ratio)),
                min(255, int(65 + 45 * ratio)),
            )
            draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=c, width=3)

        # 할머니 인물 실루엣 (흰 머리 + 분홍색 카디건)
        gx, gy = int(w * 0.42), int(h * 0.34)
        head_r = int(h * 0.075)
        draw.ellipse([gx - head_r - 6, gy - head_r - 8, gx + head_r + 6, gy + head_r], fill=(238, 238, 244))
        draw.ellipse([gx - head_r, gy - head_r, gx + head_r, gy + head_r], fill=(232, 205, 188), outline=(90, 70, 65), width=3)
        # 분홍색 카디건 상의와 단추 디테일
        draw.polygon(
            [
                (gx - int(w * 0.09), int(h * 0.82)),
                (gx - int(w * 0.065), gy + head_r + 4),
                (gx + int(w * 0.065), gy + head_r + 4),
                (gx + int(w * 0.09), int(h * 0.82)),
            ],
            fill=(228, 128, 158),
            outline=(140, 65, 90),
            width=3,
        )
        for btn_y in range(gy + head_r + 28, int(h * 0.78), 28):
            draw.ellipse([gx - 5, btn_y - 5, gx + 5, btn_y + 5], fill=(250, 230, 238))

        # 노란 장우산 (할머니가 건네는 물건)
        ux, uy = int(w * 0.60), int(h * 0.36)
        draw.chord(
            [ux - int(w * 0.13), uy - int(h * 0.12), ux + int(w * 0.13), uy + int(h * 0.12)],
            start=180,
            end=360,
            fill=(252, 212, 56),
            outline=(160, 120, 15),
            width=4,
        )
        draw.line([(ux, uy), (ux, int(h * 0.76))], fill=(240, 195, 40), width=6)
        draw.arc([ux - 24, int(h * 0.73), ux + 4, int(h * 0.80)], start=0, end=180, fill=(180, 130, 30), width=5)

    else:
        # 장면 3: 창밖으로 보이는 높은 파도가 치는 회색 바다와 노란 우산
        for y in range(h):
            t = y / max(1, h - 1)
            val = int(70 + 55 * (1 - t))
            draw.line([(0, y), (w, y)], fill=(val - 8, val, val + 12))

        # 거친 회색 바다 파도 곡선들
        for wave_idx in range(6):
            base_y = int(h * (0.44 + wave_idx * 0.085))
            pts: list[tuple[int, int]] = [(0, h)]
            for x in range(0, w + 16, 16):
                wy = base_y + int(22 * math.sin(x / 55.0 + wave_idx * 1.1) + 10 * math.cos(x / 23.0))
                pts.append((x, wy))
            pts.append((w, h))
            shade = max(35, 115 - wave_idx * 14)
            draw.polygon(pts, fill=(shade - 10, shade, shade + 15), outline=(210, 220, 230))

        # 학교 창틀 프레임
        frame_margin_x = int(w * 0.07)
        frame_margin_y = int(h * 0.08)
        draw.rectangle(
            [frame_margin_x, frame_margin_y, w - frame_margin_x, h - frame_margin_y],
            outline=(42, 48, 58),
            width=18,
        )
        draw.line([(w // 2, frame_margin_y), (w // 2, h - frame_margin_y)], fill=(48, 54, 66), width=12)
        draw.line([(frame_margin_x, h // 2), (w - frame_margin_x, h // 2)], fill=(48, 54, 66), width=10)

        # 창문 앞 노란 우산 일부
        draw.ellipse(
            [int(w * 0.68), int(h * 0.62), int(w * 0.90), int(h * 0.92)],
            fill=(245, 204, 48),
            outline=(155, 118, 20),
            width=4,
        )

    return img


def measure_edge_sharpness(img: Image.Image) -> float:
    """인접 픽셀 간 평균 절대 기울기(Mean Gradient Magnitude)로 이미지 선명도를 측정한다."""
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()
    if px is None or w < 2 or h < 2:
        return 0.0

    total_grad = 0.0
    count = 0
    step = 2
    for y in range(0, h - 1, step):
        for x in range(0, w - 1, step):
            gx = abs(float(px[x + 1, y]) - float(px[x, y]))
            gy = abs(float(px[x, y + 1]) - float(px[x, y]))
            total_grad += math.hypot(gx, gy)
            count += 1
    return round(total_grad / max(1, count), 4)


def run_confidence_aggregation_experiment() -> list[dict]:
    """실험 1: 요소별 확신도 조합에 따른 장면 확신도 집계 결과 확인."""
    scenes_data = json.loads((EXAMPLES_DIR / "scenes.json").read_text(encoding="utf-8"))["scenes"]

    # 시나리오:
    # - 학교 복도(place): low (0)
    # - 할머니(person): high (2)
    # - 우산(object): high (2)
    # - 바다(place): medium (1)
    # - 두려움(emotion): high (2, 감정 요소이므로 집계 제외)
    # - 안도감(emotion): low (0, 감정 요소이므로 집계 제외)
    elements_with_confidence = [
        {"type": "place", "name": "학교 복도", "confidence": "low"},
        {"type": "person", "name": "할머니", "confidence": "high"},
        {"type": "object", "name": "우산", "confidence": "high"},
        {"type": "place", "name": "바다", "confidence": "medium"},
        {"type": "emotion", "name": "두려움", "confidence": "high"},
        {"type": "emotion", "name": "안도감", "confidence": "low"},
    ]

    results = []
    for scene in scenes_data:
        detail = aggregate_scene_confidence_detail(
            elements_with_confidence,
            scene_element_names=scene["element_names"],
        )
        results.append(
            {
                "scene_order": scene["order"],
                "summary_ko": scene["summary_ko"],
                "element_names": scene["element_names"],
                "visual_element_count": detail.visual_element_count,
                "excluded_emotion_count": detail.excluded_emotion_count,
                "mean_score": detail.mean_score,
                "confidence_level": detail.confidence_level.value,
            }
        )
    return results


def run_blur_candidates_experiment(base_img_path: Path) -> list[dict]:
    """실험 2: 동일 원본 이미지에 대해 블러 반경 후보군(A/B/C)과 단계별 선명도 유지율 비교."""
    candidates = {
        "A_weak": BlurSettings(high_radius=0.0, medium_radius=3.0, low_radius=8.0),
        "B_default": BlurSettings(high_radius=0.0, medium_radius=6.0, low_radius=16.0),
        "C_strong": BlurSettings(high_radius=0.0, medium_radius=10.0, low_radius=28.0),
    }

    with Image.open(base_img_path) as orig:
        orig_sharpness = measure_edge_sharpness(orig)

    rows: list[dict] = []
    for cand_name, settings in candidates.items():
        for level in (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW):
            out_path = OUTPUT_DIR / f"candidate_{cand_name}_{level.value}.png"
            res = apply_confidence_blur(
                source_path=base_img_path,
                output_path=out_path,
                confidence_level=level,
                settings=settings,
            )
            with Image.open(out_path) as blurred:
                sharpness = measure_edge_sharpness(blurred)
            retention_pct = round((sharpness / orig_sharpness) * 100.0, 1) if orig_sharpness > 0 else 100.0
            rows.append(
                {
                    "candidate": cand_name,
                    "level": level.value,
                    "base_radius": res.base_radius,
                    "effective_radius": res.blur_radius,
                    "edge_sharpness": sharpness,
                    "sharpness_retention_pct": retention_pct,
                    "output_file": out_path.name,
                }
            )
    return rows


def run_resolution_normalization_experiment() -> list[dict]:
    """실험 2-2: 서로 다른 입력 해상도(640×360, 1024×1024, 1280×720, 1920×1080)에서 반경 보정 확인."""
    resolutions = [(640, 360), (1024, 1024), (1280, 720), (1920, 1080)]
    settings = BlurSettings(high_radius=0.0, medium_radius=6.0, low_radius=16.0, reference_long_edge=1280)
    rows: list[dict] = []

    for w, h in resolutions:
        src_path = OUTPUT_DIR / f"res_src_{w}x{h}.png"
        dst_path = OUTPUT_DIR / f"res_blur_medium_{w}x{h}.png"
        img = create_sample_scene_image(2, size=(w, h))
        img.save(src_path)

        res = apply_confidence_blur(
            source_path=src_path,
            output_path=dst_path,
            confidence_level=Confidence.MEDIUM,
            settings=settings,
        )
        rows.append(
            {
                "resolution": f"{w}x{h}",
                "long_edge": max(w, h),
                "base_radius": res.base_radius,
                "effective_radius": res.blur_radius,
            }
        )
    return rows


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[E1 실험] 출력 디렉토리: {OUTPUT_DIR}")

    # 1. 장면 확신도 집계 실험
    agg_results = run_confidence_aggregation_experiment()
    print("\n=== 1. 장면 확신도 집계 결과 ===")
    for item in agg_results:
        print(
            f"  장면 {item['scene_order']}: 평균={item['mean_score']:.2f} "
            f"(시각요소 {item['visual_element_count']}개, 감정제외 {item['excluded_emotion_count']}개) "
            f"-> 단계={item['confidence_level']}"
        )

    # 2. 샘플 장면 원본 이미지 3장 생성 및 단계별 후처리
    scene_Render_inputs: list[SceneRenderInput] = []
    default_blur = BlurSettings()

    for item in agg_results:
        order = item["scene_order"]
        level = Confidence(item["confidence_level"])
        orig_path = OUTPUT_DIR / f"scene_{order}_original.png"
        blur_path = OUTPUT_DIR / f"scene_{order}_blur_{level.value}.png"

        img = create_sample_scene_image(order, size=(1280, 720))
        img.save(orig_path)

        pp = apply_confidence_blur(
            source_path=orig_path,
            output_path=blur_path,
            confidence_level=level,
            settings=default_blur,
            scene_id=order,
            version_no=1,
        )
        print(
            f"  장면 {order} 후처리 완료: level={pp.confidence_level.value}, "
            f"radius={pp.blur_radius}px -> {blur_path.name}"
        )
        scene_Render_inputs.append(
            SceneRenderInput(
                order=order,
                scene_id=order,
                version_no=1,
                image_path=blur_path,
            )
        )

    # 3. 동일 장면(장면 2: 할머니와 우산)으로 후보군 A/B/C 비교
    cand_rows = run_blur_candidates_experiment(OUTPUT_DIR / "scene_2_original.png")
    print("\n=== 2. 블러 반경 후보군 비교 (장면 2 기준) ===")
    for r in cand_rows:
        print(
            f"  [{r['candidate']}] {r['level']:6s}: radius={r['effective_radius']:5.1f}px | "
            f"선명도(Gradient)={r['edge_sharpness']:6.2f} ({r['sharpness_retention_pct']:5.1f}%)"
        )

    res_rows = run_resolution_normalization_experiment()
    print("\n=== 3. 해상도별 블러 반경 자동 정규화 (medium=6.0 기준) ===")
    for r in res_rows:
        print(
            f"  해상도 {r['resolution']:9s} (긴 변 {r['long_edge']:4d}px) -> "
            f"적용 반경={r['effective_radius']:.2f}px"
        )

    # 4. FFmpeg Ken Burns + Crossfade 슬라이드 영상 합성 및 검증
    video_out = OUTPUT_DIR / "dream_slideshow_1280x720.mp4"
    render_settings = RenderSettings(
        width=1280,
        height=720,
        fps=30,
        default_scene_duration=4.0,
        transition_duration=0.5,
    )
    t0 = time.perf_counter()
    comp = compose_slideshow_video(
        scenes=scene_Render_inputs,
        output_path=video_out,
        settings=render_settings,
    )
    elapsed_sec = round(time.perf_counter() - t0, 2)

    print("\n=== 4. FFmpeg 슬라이드 영상 합성 및 검증 결과 ===")
    print(f"  파일 경로: {comp.output_path}")
    print(f"  해상도/FPS: {comp.width}x{comp.height} @ {comp.fps}fps ({comp.verification.codec})")
    print(f"  재생 길이: {comp.duration:.2f}s (예상 길이: {comp.expected_duration:.2f}s)")
    print(f"  파일 크기: {comp.verification.file_size_bytes:,} bytes")
    print(f"  렌더링 소요 시간: {elapsed_sec:.2f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
