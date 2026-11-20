"""services/repo_bridge.py에서 repositories로 옮긴 함수 (C 요청)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.enums import FailureCode, JobStatus, JobType
from app.repositories import dreams, extractions, jobs, scenes
from tests.repositories.helpers import (
    ELEMENTS_PAYLOAD,
    SCENES,
    committed_dream,
    run_concurrently,
)

GENERATED_AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _result(**overrides) -> dict:
    return {
        "final_prompt": "final prompt",
        "model": "gpt-image-1",
        "settings": {"size": "1536x1024"},
        "seed": 42,
        "image_path": "dreams/1/scenes/1/v1/original.png",
        "generated_at": GENERATED_AT,
        "confidence_level": None,
    } | overrides


@pytest.fixture
def version(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    extractions.save_extraction(db, dream.id, "after_interview", ELEMENTS_PAYLOAD, text_length=10)
    return scenes.create_scenes(db, dream.id, SCENES)[0].current_version


# --- jobs ---------------------------------------------------------------------


def test_claim_job_only_from_queued(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    job = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_SCENES)
    assert jobs.claim_job(db, job.id) is True
    assert job.status == JobStatus.RUNNING and job.started_at is not None
    assert jobs.claim_job(db, job.id) is False  # 이미 running
    assert jobs.claim_job(db, 999_999_999) is False


def test_concurrent_claim_succeeds_once(db_engine):
    with committed_dream(db_engine) as dream_id:
        with Session(db_engine) as s:
            job_id = jobs.create_job_or_get_active(s, dream_id, JobType.GENERATE_SCENES).id
            s.commit()
        results = run_concurrently(db_engine, lambda s: jobs.claim_job(s, job_id), n=5)
        assert sorted(results) == [False, False, False, False, True]


def test_list_active_job_ids_in_creation_order(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    a = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=1)
    b = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=2)
    c = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=3)
    jobs.claim_job(db, b.id)
    jobs.update_job(db, c.id, status=JobStatus.SUCCEEDED)

    ids = jobs.list_active_job_ids(db)
    assert [i for i in ids if i in {a.id, b.id, c.id}] == [a.id, b.id]
    assert a.status == JobStatus.QUEUED  # 조회만 하고 바꾸지 않음


def test_mark_queued_interrupted(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    queued = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=1)
    running = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=2)
    jobs.claim_job(db, running.id)

    assert jobs.mark_queued_interrupted(db) >= 1
    assert queued.status == JobStatus.FAILED and queued.error_code == FailureCode.INTERRUPTED
    assert queued.error_message == jobs.QUEUED_INTERRUPTED_MESSAGE and queued.finished_at is not None
    assert running.status == JobStatus.RUNNING  # running은 mark_interrupted가 맡음


# --- dreams -------------------------------------------------------------------


def test_lock_dream_returns_row(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    assert dreams.lock_dream(db, dream.id) is dream
    assert dreams.lock_dream(db, 999_999_999) is None


def test_lock_dream_blocks_other_transaction(db_engine):
    with committed_dream(db_engine) as dream_id, Session(db_engine) as holder, Session(db_engine) as waiter:
        dreams.lock_dream(holder, dream_id)
        waiter.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError):  # 앞 트랜잭션이 끝날 때까지 기다리다 시간 초과
            dreams.lock_dream(waiter, dream_id)
        waiter.rollback()
        holder.commit()  # 잠금 해제 후에는 바로 잠근다
        assert dreams.lock_dream(waiter, dream_id) is not None
        waiter.rollback()


# --- scenes -------------------------------------------------------------------


def test_save_image_result_once(db, version):
    assert scenes.save_image_result(db, version.id, **_result()) is True
    assert version.status == JobStatus.SUCCEEDED
    assert (version.image_path, version.model, version.seed, version.generated_at) == (
        "dreams/1/scenes/1/v1/original.png", "gpt-image-1", 42, GENERATED_AT
    )
    # 이미 결과가 있으면 바꾸지 않음
    assert scenes.save_image_result(db, version.id, **_result(image_path="other.png")) is False
    assert version.image_path == "dreams/1/scenes/1/v1/original.png"


def test_save_image_result_confidence_coalesce(db, version):
    version.confidence_level = None
    db.flush()
    scenes.save_image_result(db, version.id, **_result(confidence_level="low"))
    assert version.confidence_level == "low"


def test_save_image_result_keeps_existing_confidence(db, version):
    version.confidence_level = "medium"  # 장면 만들 때 미리 계산해 둔 값
    db.flush()
    scenes.save_image_result(db, version.id, **_result(confidence_level="low"))
    assert version.confidence_level == "medium"


def test_save_image_result_none_confidence_leaves_column(db, version):
    version.confidence_level = None
    db.flush()
    scenes.save_image_result(db, version.id, **_result(confidence_level=None))
    assert version.confidence_level is None


def test_failed_and_reset_scene_version(db, version):
    assert scenes.reset_failed_scene_version(db, version.id) is False  # queued는 그대로
    assert scenes.mark_scene_version_failed(db, version.id) is True
    assert version.status == JobStatus.FAILED
    assert scenes.reset_failed_scene_version(db, version.id) is True
    assert version.status == JobStatus.QUEUED

    scenes.save_image_result(db, version.id, **_result())
    assert scenes.mark_scene_version_failed(db, version.id) is False  # 이미지가 있으면 실패로 안 바꿈
    assert version.status == JobStatus.SUCCEEDED
