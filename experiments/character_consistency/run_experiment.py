"""E2 인물 일관성 실험: 조건별 장면 이미지 생성 (E2 계획서 3.3).

test_dream.json의 인물 2명 × 장면 5개를 조건 A~D로 생성해 outputs/<조건>/scene_<n>.png에 저장한다.

| 조건 | 생성 방식 |
| A 기준        | 인물 이름·관계만 넣음 |
| B 특징 주입   | A + 외형 특징 고정 문구를 모든 장면에 반복 |
| C 특징+고정   | B + 공통 화풍·구도 고정 (worker/image_gen/prompt.py의 build_prompt 그대로).
|               | OpenAI 이미지 API는 seed를 지원하지 않아 seed 고정은 빠짐 |
| D 참고 이미지 | C 프롬프트 + 1장면 이미지를 참고 이미지로 넣어 2~5장면 생성 (images.edit) |

실행 (저장소 루트에서):
    backend/.venv/Scripts/python experiments/character_consistency/run_experiment.py --dry-run
    backend/.venv/Scripts/python experiments/character_consistency/run_experiment.py
    backend/.venv/Scripts/python experiments/character_consistency/run_experiment.py --conditions A,B

- 이미 있는 이미지는 건너뛴다 (중간에 실패해도 다시 실행하면 이어서 생성, 비용 중복 없음)
- 생성 시간·토큰 사용량은 outputs/manifest.json에 쌓인다
다음 단계: make_eval.py로 블라인드 평가지 생성 → 평가 → score.py로 집계
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from worker.image_gen.prompt import Character, build_prompt

EXPERIMENT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXPERIMENT_DIR / "outputs"
MANIFEST = OUTPUT_DIR / "manifest.json"
CONDITIONS = ("A", "B", "C", "D")
REFERENCE_NOTE = (
    "Use the reference image only to keep the characters' faces, hair and clothing identical. "
    "Draw a completely new scene with a new composition: "
)


def load_dream() -> dict:
    return json.loads((EXPERIMENT_DIR / "test_dream.json").read_text(encoding="utf-8"))


def scene_prompt(dream: dict, scene: dict, condition: str) -> str:
    chars = {c["key"]: c for c in dream["characters"]}
    base = scene["prompt"].format(**{k: c["name"] for k, c in chars.items()})
    if condition == "A":
        return base + "."

    in_scene = [Character(chars[k]["name"], chars[k]["appearance"]) for k in scene["characters"]]
    if condition == "B":
        lines = "; ".join(f"{c.name} - {c.appearance}" for c in in_scene)
        return f"{base}. Characters (keep the same appearance in every scene): {lines}."
    return build_prompt(base, characters=in_scene)  # C, D


def plan(dream: dict, conditions: list[str]) -> list[dict]:
    jobs = []
    for cond in conditions:
        for scene in dream["scenes"]:
            prompt = scene_prompt(dream, scene, cond)
            use_ref = cond == "D" and scene["order"] > 1
            jobs.append({
                "condition": cond,
                "order": scene["order"],
                "mode": "edit" if use_ref else "generate",
                "prompt": REFERENCE_NOTE + prompt if use_ref else prompt,
                "path": OUTPUT_DIR / cond / f"scene_{scene['order']}.png",
            })
    return jobs


def _client():
    from app.core.config import settings
    from openai import OpenAI

    if not settings.openai_api_key:
        sys.exit("OPENAI_API_KEY가 없습니다. 저장소 루트 .env에 넣어 주세요.")
    return OpenAI(api_key=settings.openai_api_key, timeout=settings.job_timeout_seconds)


def run(jobs: list[dict]) -> None:
    from worker.image_gen.config import image_settings as cfg

    client = _client()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    common = {"model": cfg.openai_image_model, "size": cfg.image_size, "quality": cfg.image_quality, "n": 1}

    for job in jobs:
        path: Path = job["path"]
        if path.exists():
            print(f"[건너뜀] {job['condition']} 장면 {job['order']} (이미 있음)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[생성] {job['condition']} 장면 {job['order']} ({job['mode']}) ...", end=" ", flush=True)

        started = time.monotonic()
        if job["mode"] == "edit":
            reference = OUTPUT_DIR / "D" / "scene_1.png"
            with reference.open("rb") as ref:
                # gpt-image-2는 input_fidelity를 지원하지 않는다 (400 오류)
                result = client.images.edit(image=ref, prompt=job["prompt"], **common)
        else:
            result = client.images.generate(prompt=job["prompt"], **common)
        elapsed = round(time.monotonic() - started, 1)

        path.write_bytes(base64.b64decode(result.data[0].b64_json))
        usage = result.usage.model_dump() if getattr(result, "usage", None) else None
        print(f"{elapsed}초")
        manifest.append({
            "condition": job["condition"],
            "order": job["order"],
            "mode": job["mode"],
            "prompt": job["prompt"],
            "file": str(path.relative_to(EXPERIMENT_DIR)).replace("\\", "/"),
            "elapsed_seconds": elapsed,
            "usage": usage,
            "settings": {k: v for k, v in common.items() if k != "n"},
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--conditions", default=",".join(CONDITIONS), help="예: A,B (기본: A,B,C,D)")
    parser.add_argument("--dry-run", action="store_true", help="API를 부르지 않고 프롬프트와 생성 장수만 출력")
    args = parser.parse_args()

    conditions = [c.strip().upper() for c in args.conditions.split(",") if c.strip()]
    if unknown := set(conditions) - set(CONDITIONS):
        parser.error(f"알 수 없는 조건: {sorted(unknown)}")

    jobs = plan(load_dream(), conditions)
    todo = [j for j in jobs if not j["path"].exists()]
    if args.dry_run:
        for job in jobs:
            done = "있음" if job["path"].exists() else "생성 예정"
            print(f"\n[{job['condition']}-{job['order']} {job['mode']} / {done}]\n{job['prompt']}")
        print(f"\n총 {len(jobs)}장 중 새로 생성할 이미지 {len(todo)}장")
        return 0

    # 장면 순서대로 돌므로 D의 참고 이미지(1장면)가 2~5장면보다 먼저 만들어진다
    print(f"새로 생성할 이미지 {len(todo)}장")
    run(todo)
    print(f"\n완료. 결과: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
