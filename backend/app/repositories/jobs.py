"""작업 (jobs). 작업 상태는 꿈 기록 상태와 별도다 (docs/rules/job-status.md)."""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.enums import FailureCode, JobStage, JobStatus, JobType
from app.models import Job
from app.models.job import ACTIVE_JOB_STATUSES

_UNSET: Any = object()
_FINISHED = (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value)


def _active_job(db: Session, dream_id: int, type_: str, target_id: int | None) -> Job | None:
    return db.scalar(
        select(Job).where(
            Job.dream_id == dream_id,
            Job.type == type_,
            Job.target_id.is_not_distinct_from(target_id),
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
    )


def create_job_or_get_active(
    db: Session, dream_id: int, type_: JobType | str, target_id: int | None = None
) -> Job:
    """같은 꿈·종류·대상의 작업이 진행 중(queued·running)이면 그 작업을, 없으면 새 작업(queued)을 돌려준다.

    target_id: generate_image는 scene_versions.id, render_video는 renders.id,
    generate_narration·revise_scene은 scenes.id, generate_scenes는 None.
    중복 방지는 jobs의 부분 유니크 인덱스가 하므로 동시에 여러 번 불러도 진행 중 작업은 하나다.
    """
    type_ = str(type_)
    for _ in range(3):  # 기존 작업이 막 끝난 경우를 대비해 몇 번 다시 시도
        new_id = db.scalar(
            insert(Job)
            .values(dream_id=dream_id, type=type_, target_id=target_id)
            .on_conflict_do_nothing(
                index_elements=["dream_id", "type", "target_id"],
                index_where=Job.status.in_(ACTIVE_JOB_STATUSES),
            )
            .returning(Job.id)
        )
        if new_id is not None:
            return db.get(Job, new_id)
        active = _active_job(db, dream_id, type_, target_id)
        if active is not None:
            return active
    raise RuntimeError("진행 중 작업 조회에 실패했습니다.")


def get_job(db: Session, job_id: int) -> Job | None:
    return db.get(Job, job_id)


def get_active_jobs(db: Session, dream_id: int) -> list[Job]:
    """꿈 기록의 진행 중(queued·running) 작업 목록. 만든 순서대로."""
    return list(
        db.scalars(
            select(Job)
            .where(Job.dream_id == dream_id, Job.status.in_(ACTIVE_JOB_STATUSES))
            .order_by(Job.created_at, Job.id)
        )
    )


def update_job(
    db: Session,
    job_id: int,
    *,
    status: JobStatus | str = _UNSET,
    stage: JobStage | str | None = _UNSET,
    error_code: FailureCode | str | None = _UNSET,
    error_message: str | None = _UNSET,
    attempt: int = _UNSET,
) -> Job | None:
    """넘긴 값만 바꾼다. 작업이 없으면 None.

    - status가 running이 되면 started_at을 (처음 한 번) 기록한다.
    - status가 succeeded·failed가 되면 finished_at을 기록한다.
    """
    job = db.get(Job, job_id)
    if job is None:
        return None
    if stage is not _UNSET:
        job.stage = None if stage is None else str(stage)
    if error_code is not _UNSET:
        job.error_code = None if error_code is None else str(error_code)
    if error_message is not _UNSET:
        job.error_message = error_message
    if attempt is not _UNSET:
        job.attempt = attempt
    if status is not _UNSET:
        job.status = str(status)
        if job.status == JobStatus.RUNNING and job.started_at is None:
            job.started_at = func.now()
        if job.status in _FINISHED:
            job.finished_at = func.now()
    db.flush()
    db.refresh(job)  # func.now() 값 읽기
    return job


def mark_interrupted(db: Session) -> int:
    """서버 재시작 시 호출. running으로 남은 작업을 failed(INTERRUPTED)로 바꾸고, 바꾼 개수를 돌려준다."""
    result = db.execute(
        update(Job)
        .where(Job.status == JobStatus.RUNNING.value)
        .values(
            status=JobStatus.FAILED.value,
            error_code=FailureCode.INTERRUPTED.value,
            error_message="서버가 다시 시작되어 작업이 중단되었습니다.",
            finished_at=func.now(),
        )
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount


QUEUED_INTERRUPTED_MESSAGE = "서버가 다시 시작되어 작업이 중단되었습니다. 다시 시도해 주세요."


def claim_job(db: Session, job_id: int) -> bool:
    """queued인 작업만 running으로 바꾸고 started_at을 기록한다. 바뀌었으면 True.

    WHERE status = 'queued' 조건으로 바꾸므로 두 실행기가 같은 작업을 동시에 시작해도 한 쪽만 True다.
    """
    result = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.QUEUED.value)
        .values(status=JobStatus.RUNNING.value, started_at=func.now())
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


def list_active_job_ids(db: Session) -> list[int]:
    """행을 바꾸지 않고 queued·running 작업 id를 만든 순서(created_at, id)대로 돌려준다.

    서버 재시작 처리 때 mark_interrupted·mark_queued_interrupted보다 먼저 불러 후처리 대상을 얻는다.
    """
    return list(
        db.scalars(select(Job.id).where(Job.status.in_(ACTIVE_JOB_STATUSES)).order_by(Job.created_at, Job.id))
    )


def mark_queued_interrupted(db: Session) -> int:
    """서버 재시작 시 호출. queued로 남은 작업을 failed(INTERRUPTED)로 바꾸고, 바꾼 개수를 돌려준다.

    BackgroundTasks에 있던 작업은 재시작하면 사라지므로 queued 행은 다시 실행되지 않는다.
    """
    result = db.execute(
        update(Job)
        .where(Job.status == JobStatus.QUEUED.value)
        .values(
            status=JobStatus.FAILED.value,
            error_code=FailureCode.INTERRUPTED.value,
            error_message=QUEUED_INTERRUPTED_MESSAGE,
            finished_at=func.now(),
        )
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount
