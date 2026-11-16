from sqlalchemy import func, select

from app.core.enums import FailureCode, JobStage, JobStatus, JobType
from app.models import Job
from app.repositories import dreams, jobs
from tests.repositories.helpers import committed_dream, run_concurrently


def _active_count(db, dream_id) -> int:
    return db.scalar(
        select(func.count()).select_from(Job).where(Job.dream_id == dream_id, Job.status.in_(["queued", "running"]))
    )


def test_create_job_returns_existing_active_job(db):
    """완료 기준: 같은 꿈에 같은 작업을 연속으로 5번 만들어도 진행 중 작업은 1개."""
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    made = [jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_SCENES) for _ in range(5)]
    assert len({job.id for job in made}) == 1
    assert made[0].status == JobStatus.QUEUED
    assert _active_count(db, dream.id) == 1


def test_new_job_after_previous_finished(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    first = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_SCENES)
    jobs.update_job(db, first.id, status=JobStatus.FAILED, error_code=FailureCode.TIMEOUT)
    second = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_SCENES)
    assert second.id != first.id


def test_different_targets_are_separate_jobs(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    a = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=1)
    b = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=2)
    assert a.id != b.id
    assert jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=1).id == a.id


def test_concurrent_create_job_makes_one(db_engine):
    with committed_dream(db_engine) as dream_id:
        ids = run_concurrently(
            db_engine,
            lambda s: jobs.create_job_or_get_active(s, dream_id, JobType.GENERATE_SCENES).id,
            n=5,
        )
        assert len(set(ids)) == 1


def test_update_job_records_times(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    job = jobs.create_job_or_get_active(db, dream.id, JobType.RENDER_VIDEO, target_id=1)
    assert job.started_at is None and job.finished_at is None

    job = jobs.update_job(db, job.id, status=JobStatus.RUNNING, stage=JobStage.COMPOSING, attempt=1)
    assert job.stage == JobStage.COMPOSING and job.attempt == 1
    assert job.started_at is not None and job.finished_at is None

    job = jobs.update_job(db, job.id, status=JobStatus.FAILED, error_code=FailureCode.RENDER_FAILED, error_message="x")
    assert job.error_code == FailureCode.RENDER_FAILED and job.finished_at is not None
    assert job.stage == JobStage.COMPOSING  # 넘기지 않은 값은 그대로

    assert jobs.get_job(db, job.id) is job
    assert jobs.get_job(db, 999_999_999) is None
    assert jobs.update_job(db, 999_999_999, status=JobStatus.RUNNING) is None


def test_mark_interrupted_fails_only_running_jobs(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    running = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=1)
    queued = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=2)
    jobs.update_job(db, running.id, status=JobStatus.RUNNING)

    assert jobs.mark_interrupted(db) >= 1  # 다른 테스트가 남긴 running 작업은 없지만 >=로 안전하게
    assert running.status == JobStatus.FAILED
    assert running.error_code == FailureCode.INTERRUPTED and running.finished_at is not None
    assert queued.status == JobStatus.QUEUED
