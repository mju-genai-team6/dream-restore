"""블라인드 평가지 만들기 (E2 계획서 3.3 평가 방식).

같은 인물이 나오는 두 장면을 짝지어(인물이 처음 나온 장면 vs 이후 장면) 조건을 숨기고 섞는다.
평가자는 두 그림 속 인물이 같은 사람으로 보이는지 1~5점으로 답한다 (4점 이상 = 같은 인물로 인식, DB 지표 뷰와 같은 기준).

실행 (저장소 루트에서, run_experiment.py 다음):
    backend/.venv/Scripts/python experiments/character_consistency/make_eval.py

만들어지는 파일 (outputs/eval/, Git 제외):
    images/<번호>_L.png, <번호>_R.png  조건을 알 수 없는 이름으로 복사한 이미지
    eval.html                          평가자에게 보여 줄 페이지 (브라우저로 열기)
    eval_sheet.csv                     평가자별로 복사해 score 칸을 채우는 시트
    answer_key.json                    번호 → 조건·인물·장면 (평가자에게 보여 주지 않음)
"""
from __future__ import annotations

import csv
import html
import json
import random
import shutil
import sys
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXPERIMENT_DIR / "outputs"
EVAL_DIR = OUTPUT_DIR / "eval"
CONDITIONS = ("A", "B", "C", "D")
SHUFFLE_SEED = 20261116  # 같은 시드면 같은 순서 (평가지를 다시 만들어도 번호 유지)


def build_pairs(dream: dict) -> list[dict]:
    pairs = []
    for cond in CONDITIONS:
        for char in dream["characters"]:
            orders = [s["order"] for s in dream["scenes"] if char["key"] in s["characters"]]
            first, rest = orders[0], orders[1:]
            for other in rest:
                left = OUTPUT_DIR / cond / f"scene_{first}.png"
                right = OUTPUT_DIR / cond / f"scene_{other}.png"
                if left.exists() and right.exists():
                    pairs.append({"condition": cond, "character": char["key"], "label_ko": char["label_ko"],
                                  "scenes": [first, other], "left": left, "right": right})
    return pairs


def write_html(rows: list[dict]) -> None:
    cards = "\n".join(
        f"""<section><h2>{r['pair_id']}. {html.escape(r['label_ko'])}</h2>
<div class="pair"><img src="images/{r['pair_id']}_L.png" alt=""><img src="images/{r['pair_id']}_R.png" alt=""></div>
<p>두 그림의 <b>{html.escape(r['label_ko'])}</b>가 같은 사람으로 보이나요? 1(전혀 아님) ~ 5(확실히 같음)</p></section>"""
        for r in rows
    )
    page = f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>인물 일관성 평가</title>
<style>body{{font-family:sans-serif;max-width:1100px;margin:auto;padding:16px}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}img{{width:100%;border-radius:6px}}
section{{margin-bottom:40px}}</style>
<h1>인물 일관성 평가</h1>
<p>각 번호마다 두 그림 속 인물이 같은 사람으로 보이는지 eval_sheet.csv의 score 칸에 1~5점으로 적어 주세요.
배경·화풍이 달라도 얼굴, 머리, 옷 등 인물만 보고 판단합니다.</p>
{cards}</html>"""
    (EVAL_DIR / "eval.html").write_text(page, encoding="utf-8")


def main() -> int:
    dream = json.loads((EXPERIMENT_DIR / "test_dream.json").read_text(encoding="utf-8"))
    pairs = build_pairs(dream)
    if not pairs:
        print("평가할 이미지가 없습니다. run_experiment.py를 먼저 실행하세요.")
        return 1

    random.Random(SHUFFLE_SEED).shuffle(pairs)
    if EVAL_DIR.exists():
        shutil.rmtree(EVAL_DIR)
    (EVAL_DIR / "images").mkdir(parents=True)

    rows, key = [], {}
    for i, pair in enumerate(pairs, start=1):
        pid = f"{i:02d}"
        left, right = pair["left"], pair["right"]
        if random.Random(SHUFFLE_SEED + i).random() < 0.5:  # 좌우도 섞는다
            left, right = right, left
        shutil.copy(left, EVAL_DIR / "images" / f"{pid}_L.png")
        shutil.copy(right, EVAL_DIR / "images" / f"{pid}_R.png")
        rows.append({"pair_id": pid, "label_ko": pair["label_ko"]})
        key[pid] = {"condition": pair["condition"], "character": pair["character"], "scenes": pair["scenes"]}

    with (EVAL_DIR / "eval_sheet.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["pair_id", "character", "score"])
        writer.writerows([r["pair_id"], r["label_ko"], ""] for r in rows)
    (EVAL_DIR / "answer_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html(rows)

    counts = {c: sum(1 for p in pairs if p["condition"] == c) for c in CONDITIONS}
    print(f"평가 쌍 {len(pairs)}개 (조건별 {counts})")
    print(f"평가자에게 줄 것: {EVAL_DIR / 'eval.html'}, images/ 폴더, eval_sheet.csv 사본")
    print("answer_key.json은 평가자에게 보여 주지 마세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
