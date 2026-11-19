"""S4 확신도 표현 평가 도구 (E1). 프로토콜: experiments/confidence_blur/results.md 4장.

1) 참가자별 비교 영상 만들기 (완성된 영상이 있는 꿈 하나):
   python scripts/e1_evaluation.py pair --dream-id 2 --participant 1
   → storage/eval/p1_dream2/video_1.mp4, video_2.mp4 (참가자에게는 이 두 개만 보여 준다)
     key.json에 어느 쪽이 blur / no_blur인지 기록. 홀수 참가자는 blur 먼저, 짝수는 no_blur 먼저.
2) 응답 저장·집계 (CSV 헤더: participant,dream_id,render_id,video,score,too_blurry,note):
   python scripts/e1_evaluation.py import responses.csv
   → key.json으로 video(1·2)를 조건으로 바꿔 evaluations(kind='confidence')에 저장하고 요약을 출력.
     같은 참가자·꿈·조건 응답이 이미 있으면 다시 넣지 않는다.
"""

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Evaluation, SceneVersion
from app.repositories import renders as render_repo
from app.repositories.evaluations import save_evaluation
from worker.render.video import SceneRenderInput, compose_slideshow_video

KIND = "confidence"
CONDITIONS = ("blur", "no_blur")


def eval_dir(participant: int, dream_id: int) -> Path:
    return settings.storage_path / "eval" / f"p{participant}_dream{dream_id}"


def order_for(participant: int) -> tuple[str, str]:
    """제시 순서 교차: 홀수 참가자는 blur 먼저."""
    return CONDITIONS if participant % 2 else CONDITIONS[::-1]


def make_pair(dream_id: int, participant: int) -> Path:
    with SessionLocal() as db:
        latest = render_repo.get_latest_render(db, dream_id)
        if latest is None or not latest.render.video_path:
            raise SystemExit(f"꿈 {dream_id}에 완성된 영상이 없습니다. 먼저 영상을 만들어 주세요.")
        render = latest.render
        versions = [db.get(SceneVersion, vid) for vid in render.scene_version_ids]

    out = eval_dir(participant, dream_id)
    out.mkdir(parents=True, exist_ok=True)
    videos = {"blur": settings.storage_path / render.video_path}
    # no_blur: 같은 장면 버전의 원본 이미지로 같은 규격의 영상 (블러만 다름)
    no_blur = out / "no_blur.mp4"
    compose_slideshow_video(
        [
            SceneRenderInput(scene_id=v.scene_id, version_no=v.version_no, order=i,
                             image_path=settings.storage_path / v.image_path)
            for i, v in enumerate(versions, start=1)
        ],
        no_blur,
    )
    videos["no_blur"] = no_blur

    key = {"participant": participant, "dream_id": dream_id, "render_id": render.id}
    for n, condition in enumerate(order_for(participant), start=1):
        shutil.copyfile(videos[condition], out / f"video_{n}.mp4")
        key[f"video_{n}"] = condition
    no_blur.unlink()
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def read_responses(path: Path) -> list[dict]:
    """CSV를 읽어 key.json으로 조건을 붙인다. 형식이 틀리면 저장 전에 멈춘다."""
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:  # 엑셀·구글폼 CSV의 BOM 허용
        for line_no, raw in enumerate(csv.DictReader(f), start=2):
            try:
                participant, dream_id = int(raw["participant"]), int(raw["dream_id"])
                score, video = int(raw["score"]), int(raw["video"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SystemExit(f"{path}:{line_no} 숫자 칸이 비었거나 잘못됐습니다: {exc}") from exc
            if not 1 <= score <= 5 or video not in (1, 2):
                raise SystemExit(f"{path}:{line_no} score는 1~5, video는 1 또는 2여야 합니다.")
            key_file = eval_dir(participant, dream_id) / "key.json"
            if not key_file.exists():
                raise SystemExit(f"{path}:{line_no} {key_file}이 없습니다. pair를 먼저 실행하세요.")
            key = json.loads(key_file.read_text(encoding="utf-8"))
            rows.append({
                "participant": participant, "dream_id": dream_id, "render_id": key["render_id"],
                "condition": key[f"video_{video}"], "first": key["video_1"], "score": score,
                "too_blurry": (raw.get("too_blurry") or "").strip().lower() in {"1", "y", "yes", "예", "o", "true"},
                "note": (raw.get("note") or "").strip(),
            })
    return rows


def summarize(rows: list[dict]) -> str:
    by_cond = defaultdict(list)
    by_order = defaultdict(list)
    for r in rows:
        by_cond[r["condition"]].append(r["score"])
        by_order[(r["condition"], "먼저" if r["first"] == r["condition"] else "나중")].append(r["score"])
    lines = [f"응답 {len(rows)}개, 참가자 {len({r['participant'] for r in rows})}명"]
    for c in CONDITIONS:
        scores = by_cond.get(c, [])
        if scores:
            dist = " ".join(f"{s}점:{scores.count(s)}" for s in range(1, 6))
            lines.append(f"- {c}: 평균 {mean(scores):.2f} (n={len(scores)}) | {dist}")
    for (c, pos), scores in sorted(by_order.items()):
        lines.append(f"  · {c} {pos} 본 경우 평균 {mean(scores):.2f} (n={len(scores)})")
    blurry = [r for r in rows if r["condition"] == "blur" and r["too_blurry"]]
    lines.append(f"- 너무 흐리다고 답한 blur 응답: {len(blurry)}개")
    lines += [f"  · p{r['participant']} 꿈{r['dream_id']}: {r['note']}" for r in rows if r["note"]]
    return "\n".join(lines)


def import_responses(path: Path) -> None:
    rows = read_responses(path)
    saved = 0
    with SessionLocal() as db:
        for r in rows:
            # shortcut: evaluations에 참가자 칸이 없어 (꿈, render, 조건)으로 중복을 판단한다. 한 꿈을 여러 명이 평가하면 칸 추가 필요
            exists = db.scalar(select(Evaluation.id).where(
                Evaluation.kind == KIND, Evaluation.dream_id == r["dream_id"],
                Evaluation.render_id == r["render_id"], Evaluation.condition == r["condition"],
            ))
            if exists is None:
                save_evaluation(db, dream_id=r["dream_id"], kind=KIND, condition=r["condition"],
                                score=r["score"], render_id=r["render_id"])
                saved += 1
        db.commit()
    print(f"저장 {saved}개 (중복 {len(rows) - saved}개 건너뜀)\n{summarize(rows)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="S4 확신도 표현 평가 도구")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair", help="참가자별 비교 영상 만들기")
    p.add_argument("--dream-id", type=int, required=True)
    p.add_argument("--participant", type=int, required=True)
    i = sub.add_parser("import", help="응답 CSV 저장·집계")
    i.add_argument("csv", type=Path)
    args = parser.parse_args()
    if args.cmd == "pair":
        out = make_pair(args.dream_id, args.participant)
        print(f"{out}/video_1.mp4, video_2.mp4 를 순서대로 보여 주세요 (정답: {out}/key.json)")
    else:
        import_responses(args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
