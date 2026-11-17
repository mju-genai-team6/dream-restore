"""평가 결과 집계: 조건별 '같은 인물로 인식'한 비율 (E2 계획서 6절 완료 기준).

평가자들이 채운 eval_sheet 사본을 outputs/eval/responses/ 에 넣고 실행한다 (파일 이름 자유, .csv).
4점 이상을 "같은 인물로 인식"으로 센다 (DB 지표 뷰 v_character_consistency와 같은 기준).

실행 (저장소 루트에서):
    backend/.venv/Scripts/python experiments/character_consistency/score.py
출력된 표를 results.md에 붙여 넣는다.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent / "outputs" / "eval"
RECOGNIZED_MIN_SCORE = 4
CONDITION_NAMES = {"A": "A 기준", "B": "B 특징 주입", "C": "C 특징+고정", "D": "D 참고 이미지"}


def main() -> int:
    key = json.loads((EVAL_DIR / "answer_key.json").read_text(encoding="utf-8"))
    files = sorted((EVAL_DIR / "responses").glob("*.csv"))
    if not files:
        print(f"{EVAL_DIR / 'responses'} 에 채운 평가지(.csv)를 넣어 주세요.")
        return 1

    scores: dict[str, list[int]] = defaultdict(list)
    by_char: dict[tuple[str, str], list[int]] = defaultdict(list)
    for path in files:
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                value = (row.get("score") or "").strip()
                if not value:
                    continue
                score = int(value)
                if not 1 <= score <= 5:
                    raise ValueError(f"{path.name} {row['pair_id']}: 점수는 1~5 ({score})")
                info = key[row["pair_id"].zfill(2)]
                scores[info["condition"]].append(score)
                by_char[(info["condition"], info["character"])].append(score)

    def line(values: list[int]) -> str:
        ok = sum(v >= RECOGNIZED_MIN_SCORE for v in values)
        return f"{len(values)} | {ok} | {ok / len(values):.0%} | {sum(values) / len(values):.2f}"

    print(f"평가자 {len(files)}명\n")
    print("| 조건 | 응답 수 | 인식 수(4점 이상) | 인식 비율 | 평균 점수 |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for cond, name in CONDITION_NAMES.items():
        if scores[cond]:
            print(f"| {name} | {line(scores[cond])} |")

    print("\n| 조건 | 인물 | 응답 수 | 인식 수 | 인식 비율 | 평균 점수 |")
    print("| --- | --- | ---: | ---: | ---: | ---: |")
    for (cond, char), values in sorted(by_char.items()):
        print(f"| {CONDITION_NAMES[cond]} | {char} | {line(values)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
