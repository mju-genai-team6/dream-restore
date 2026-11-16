"""scripts/seed.py 샘플 데이터 확인 (이관 문서 7장)."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.enums import DreamStatus
from app.repositories import dreams, extractions, interview, renders, scenes

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seeded(db):
    made = _load("seed").seed(db)
    return {DreamStatus(d.status): d for d in made}


def test_one_sample_per_status(seeded):
    assert set(seeded) == set(DreamStatus)


def test_recorded_sample(db, seeded):
    dream = seeded[DreamStatus.RECORDED]
    assert dream.raw_text and dream.confirmed_text is None
    assert interview.get_progress(db, dream.id) == (0, 0)


def test_interviewing_sample_is_in_progress(db, seeded):
    dream = seeded[DreamStatus.INTERVIEWING]
    answered, total = interview.get_progress(db, dream.id)
    assert 0 < answered < total
    assert extractions.list_elements(db, dream.id)  # 원문 추출 요소


def test_scenes_ready_sample_has_partial_images(db, seeded):
    dream = seeded[DreamStatus.SCENES_READY]
    statuses = [s.current_version.status for s in scenes.list_scenes(db, dream.id)]
    assert statuses == ["succeeded", "running", "queued"]
    assert scenes.all_images_done(db, dream.id) is False


def test_images_ready_sample(db, seeded):
    dream = seeded[DreamStatus.IMAGES_READY]
    assert scenes.all_images_done(db, dream.id) is True
    assert renders.get_latest_render(db, dream.id) is None


def test_rendered_sample_uses_d_example(db, seeded):
    dream = seeded[DreamStatus.RENDERED]
    elements = extractions.list_elements(db, dream.id)
    assert {e.name for e in elements} >= {"학교 복도", "할머니", "우산", "바다"}
    assert all(e.confidence for e in elements if e.type != "emotion")
    latest = renders.get_latest_render(db, dream.id)
    assert latest.is_latest is True and latest.render.video_path.endswith("video.mp4")


def test_list_and_views_have_sample_rows(db, seeded):
    ids = {d.id for d in seeded.values()}
    page = dreams.list_dreams(db, limit=50)
    listed = [i for i in page.items if i.dream.id in ids]
    assert [i.dream.status for i in listed] == [  # 최신순 = SAMPLE_DREAMS 역순
        "recorded", "interviewing", "scenes_ready", "images_ready", "rendered"
    ]
    assert listed[-1].thumbnail_path is not None

    comparison = db.execute(
        text("SELECT * FROM v_interview_comparison WHERE dream_id = :id"), {"id": seeded[DreamStatus.RENDERED].id}
    ).one()
    assert comparison.element_increase == 1 and comparison.text_length_increase > 0
    timing = db.execute(
        text("SELECT * FROM v_processing_time WHERE dream_id = :id"), {"id": seeded[DreamStatus.RENDERED].id}
    ).one()
    assert timing.scene_split_seconds == 14 and timing.render_seconds == 25 and timing.image_job_count == 3


def test_reset_refuses_non_local_db(monkeypatch):
    reset_db = _load("reset_db")
    with pytest.raises(SystemExit):
        reset_db._check_local("postgresql+psycopg://u:p@prod.example.com:5432/dream")
    monkeypatch.setattr(reset_db.settings, "app_env", "production")
    with pytest.raises(SystemExit):
        reset_db._check_local("postgresql+psycopg://u:p@localhost:5432/dream")
