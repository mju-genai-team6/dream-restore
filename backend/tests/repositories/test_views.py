"""지표 뷰 4개가 SQL 한 번으로 기대한 값을 내는지 확인한다 (이관 문서 6장)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.core.enums import JobStatus, JobType
from app.models import Job
from app.repositories import dreams, evaluations, extractions

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _rows(db, view: str, where: str = "", **params) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(f"SELECT * FROM {view} {where}"), params)]


def _elements(n: int) -> dict:
    return {"elements": [{"type": "person", "name": f"요소{i}", "description": ""} for i in range(n)]}


def test_interview_comparison(db):
    done = dreams.create_dream(db, input_type="text", raw_text="원문")
    extractions.save_extraction(db, done.id, "raw", _elements(3), text_length=100)
    extractions.save_extraction(db, done.id, "after_interview", _elements(4), text_length=150)
    extractions.save_extraction(db, done.id, "after_interview", _elements(6), text_length=180)  # 재추출: 최신만

    pending = dreams.create_dream(db, input_type="text", raw_text="인터뷰 전")
    extractions.save_extraction(db, pending.id, "raw", _elements(2), text_length=50)

    rows = {r["dream_id"]: r for r in _rows(db, "v_interview_comparison", "WHERE dream_id IN (:a, :b)", a=done.id, b=pending.id)}
    assert rows[done.id] | {"created_at": None} == {
        "dream_id": done.id,
        "created_at": None,
        "raw_element_count": 3,
        "after_element_count": 6,
        "element_increase": 3,
        "raw_text_length": 100,
        "after_text_length": 180,
        "text_length_increase": 80,
    }
    assert rows[pending.id]["after_element_count"] is None  # 인터뷰 전에는 비어 있음
    assert rows[pending.id]["element_increase"] is None


def test_confidence_evaluation(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    for condition, score in [("blur", 4), ("blur", 5), ("blur", 3), ("no_blur", 2)]:
        evaluations.save_evaluation(db, dream_id=dream.id, kind="confidence", condition=condition, score=score)
    evaluations.save_evaluation(db, dream_id=dream.id, kind="character", condition="blur", score=1)  # 다른 평가는 제외

    rows = {r["condition"]: r for r in _rows(db, "v_confidence_evaluation")}
    assert rows["blur"]["response_count"] == 3 and rows["blur"]["avg_score"] == Decimal("4.00")
    assert rows["no_blur"]["response_count"] == 1 and rows["no_blur"]["avg_score"] == Decimal("2.00")


def test_character_consistency(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    for condition, score in [("with_world", 5), ("with_world", 4), ("with_world", 2), ("without_world", 3)]:
        evaluations.save_evaluation(db, dream_id=dream.id, kind="character", condition=condition, score=score)

    rows = {r["condition"]: r for r in _rows(db, "v_character_consistency")}
    assert rows["with_world"]["response_count"] == 3
    assert rows["with_world"]["recognized_count"] == 2
    assert rows["with_world"]["recognized_ratio"] == Decimal("0.667")
    assert rows["without_world"]["recognized_ratio"] == Decimal("0.000")


def _job(db, dream_id, type_, start_s, end_s, status=JobStatus.SUCCEEDED, target_id=None):
    db.add(
        Job(
            dream_id=dream_id,
            type=type_,
            target_id=target_id,
            status=status.value,
            started_at=T0 + timedelta(seconds=start_s),
            finished_at=T0 + timedelta(seconds=end_s),
        )
    )
    db.flush()


def test_processing_time(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    _job(db, dream.id, JobType.GENERATE_SCENES, 0, 30, status=JobStatus.FAILED)  # 실패는 제외
    _job(db, dream.id, JobType.GENERATE_SCENES, 40, 52)
    _job(db, dream.id, JobType.GENERATE_IMAGE, 60, 80, target_id=1)
    _job(db, dream.id, JobType.GENERATE_IMAGE, 61, 95, target_id=2)
    _job(db, dream.id, JobType.GENERATE_IMAGE, 62, 90, target_id=3)
    _job(db, dream.id, JobType.RENDER_VIDEO, 120, 145, target_id=1)

    untouched = dreams.create_dream(db, input_type="text", raw_text="작업 없음")

    rows = _rows(db, "v_processing_time", "WHERE dream_id IN (:a, :b)", a=dream.id, b=untouched.id)
    assert len(rows) == 1  # 성공한 작업이 없는 꿈은 나오지 않는다
    row = rows[0]
    assert row["scene_split_seconds"] == 12
    assert row["image_gen_seconds"] == 35  # 60초 시작 ~ 95초 끝
    assert row["image_job_count"] == 3
    assert row["render_seconds"] == 25
