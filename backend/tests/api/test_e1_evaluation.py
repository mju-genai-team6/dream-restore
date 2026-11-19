"""S4 평가 도구 (scripts/e1_evaluation.py): 비교 영상 → 응답 CSV 저장·집계."""
import json

from sqlalchemy import select

from app.models import Evaluation
from scripts import e1_evaluation as ev
from tests.api.test_renders_api import _images_ready_dream, client, storage  # noqa: F401  # storage는 autouse


def test_pair_then_import(session_factory, read_db, storage, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(ev, "SessionLocal", session_factory)
    dream_id = _images_ready_dream(session_factory, storage)
    render_id = client.post(f"/dreams/{dream_id}/renders").json()["render_id"]

    out = ev.make_pair(dream_id, participant=2)  # 짝수 참가자는 no_blur 먼저

    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    assert key == {"participant": 2, "dream_id": dream_id, "render_id": render_id,
                   "video_1": "no_blur", "video_2": "blur"}
    assert (out / "video_1.mp4").stat().st_size > 0 and (out / "video_2.mp4").stat().st_size > 0
    assert sorted(p.name for p in out.iterdir()) == ["key.json", "video_1.mp4", "video_2.mp4"]

    csv_file = tmp_path / "responses.csv"
    csv_file.write_text(
        "﻿participant,dream_id,render_id,video,score,too_blurry,note\n"
        f"2,{dream_id},{render_id},1,2,,\n"
        f"2,{dream_id},{render_id},2,4,예,바다 장면이 너무 흐림\n",
        encoding="utf-8",
    )
    rows = ev.read_responses(csv_file)
    assert [(r["condition"], r["score"], r["too_blurry"]) for r in rows] == [("no_blur", 2, False), ("blur", 4, True)]
    summary = ev.summarize(rows)
    assert "blur: 평균 4.00" in summary and "no_blur: 평균 2.00" in summary and "바다 장면" in summary

    ev.import_responses(csv_file)
    ev.import_responses(csv_file)  # 다시 넣어도 중복 저장 안 함
    saved = read_db.scalars(select(Evaluation).order_by(Evaluation.id)).all()
    assert [(e.kind, e.condition, e.score, e.render_id) for e in saved] == [
        ("confidence", "no_blur", 2, render_id), ("confidence", "blur", 4, render_id)
    ]


def test_read_responses_rejects_bad_score(tmp_path, storage):  # noqa: F811
    bad = tmp_path / "bad.csv"
    bad.write_text("participant,dream_id,render_id,video,score\n1,1,1,1,7\n", encoding="utf-8")
    try:
        ev.read_responses(bad)
    except SystemExit as exc:
        assert "score는 1~5" in str(exc)
    else:
        raise AssertionError("잘못된 점수를 통과시킴")
