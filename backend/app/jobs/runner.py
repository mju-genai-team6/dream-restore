"""작업 실행기.

- 작업 상태는 jobs 테이블에 저장한다. 요청 세션은 응답 뒤 닫히므로 작업마다 새 세션을 연다.
- 같은 꿈에 같은 종류의 작업이 진행 중이면 기존 jobId 반환 (jobs/submit.py, create_job_or_get_active)
- JobError(retryable=True)는 settings.job_max_retries회까지 자동 재시도. CONTENT_POLICY는 바로 실패
- JobError가 아닌 예외는 재시도 없이 실패. error_code는 NULL(API에서 INTERNAL_ERROR)
- 성공 후처리(on_success)와 succeeded는 같은 세션에서 한 번에 commit한다. 후처리가 실패하면 핸들러는 다시 실행하지 않는다
- 후처리가 돌려준 다음 작업은 commit 뒤에 행을 만들고 enqueue로 실행한다. 요청의 BackgroundTasks는 쓰지 않는다
- on_failure는 최종 실패와 서버 시작 시 INTERRUPTED에서만 호출한다. 재시도 중간에는 호출하지 않는다
- 실패 후처리가 예외를 내도 실행기는 멈추지 않는다. 작업은 그 전에 failed로 commit되어 있다
- 시작 시 claim_job으로 queued를 running으로 한 번만 가져간다. 못 가져가면 핸들러·이벤트·후처리 없이 끝낸다
- 재시도는 이미 가져온 작업의 루프 안에서 이어지므로 claim_job을 다시 부르지 않는다
- SSE(publish_job_event)는 commit 뒤에 보낸다
- 서버 재시작 시 running·queued 작업은 INTERRUPTED로 실패 처리 (recover_interrupted)
- 이미지 생성 동시 요청 수는 settings.image_max_concurrency로 제한 (C-S3-02)
"""
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

# 작업 함수 등록(@register). worker가 registry를 import하므로 registry가 아니라 여기서 불러온다
import app.jobs.handlers.scenes  # noqa: F401
import worker.image_gen.generate
import worker.render.handler
import worker.render.narration  # noqa: F401
from app.core.config import settings
from app.core.enums import FailureCode, JobStage, JobStatus
from app.db.session import SessionLocal
from app.jobs.context import JobError
from app.jobs.registry import FollowUp, get_handler, get_on_failure, get_on_success
from app.models import Job
from app.repositories import jobs as job_repo
from app.services import repo_bridge
from app.services.events import publish_job_event
from app.services.job_views import job_summary
from app.services.transactions import commit, rollback
from app.storage import paths

INTERNAL_ERROR_MESSAGE = "처리 중 오류가 발생했습니다. 다시 시도해 주세요."

# 테스트에서 테스트 DB 세션으로 바꿔 끼운다
session_factory = SessionLocal

logger = logging.getLogger(__name__)

_PATH_KINDS = {
    "scene_original": paths.scene_original,
    "scene_blur": paths.scene_blur,
    "scene_narration": paths.scene_narration,
    "render_video": paths.render_video,
}


def _save(db: Session, job_id: int, **changes: Any) -> Job:
    """jobs 행을 바꾸고 바로 commit한 뒤 이벤트를 보낸다."""
    job = job_repo.update_job(db, job_id, **changes)
    if job is None:
        raise RuntimeError(f"작업 {job_id}이 없습니다.")
    commit(db)
    publish_job_event(job_summary(job))
    return job


class RunnerContext:
    """app/jobs/context.py의 JobContext 구현."""

    def __init__(self, db: Session, job: Job):
        self.db = db
        self.job_id = job.id
        self.dream_id = job.dream_id
        self.logger = logging.getLogger(f"app.jobs.{job.type}")

    def report_stage(self, stage: JobStage) -> None:
        _save(self.db, self.job_id, stage=stage)

    def path_for(self, kind: str, **ids) -> Path:
        build = _PATH_KINDS.get(kind)
        if build is None:
            raise ValueError(f"알 수 없는 경로 종류입니다: {kind}")
        ids.setdefault("dream_id", self.dream_id)
        return settings.storage_path / build(**ids)

    def tmp_dir(self) -> Path:
        return settings.storage_path / paths.job_tmp(self.job_id)


def schedule(background_tasks: BackgroundTasks, job_id: int, payload: dict | None = None) -> None:
    """응답을 보낸 뒤 실행한다. ORM 객체는 요청 세션과 함께 닫히므로 id만 넘긴다."""
    background_tasks.add_task(run_job, job_id, payload or {})


def enqueue(job_id: int, payload: dict | None = None) -> None:
    """요청의 BackgroundTasks 없이 작업을 실행한다. commit된 뒤의 다음 작업에 쓴다."""
    threading.Thread(target=run_job, args=(job_id, payload or {}), daemon=True).start()


def run_job(job_id: int, payload: dict) -> None:
    with session_factory() as db:
        try:
            _run(db, job_id, payload)
        except Exception:
            logger.exception("작업 %s 실행 중 실행기 오류", job_id)
            rollback(db)
            _fail_after_runner_error(db, job_id)
        finally:
            shutil.rmtree(settings.storage_path / paths.job_tmp(job_id), ignore_errors=True)


def _fail_after_runner_error(db: Session, job_id: int) -> None:
    try:
        _fail(db, job_id, None, INTERNAL_ERROR_MESSAGE)
    except Exception:
        logger.exception("작업 %s 실패 기록 실패", job_id)
        rollback(db)


def _call_on_failure(db: Session, job: Job) -> None:
    """실패가 commit된 뒤에 부른다. 후처리 예외는 로그로 남기고 실행을 계속한다."""
    hook = get_on_failure(job.type)
    if hook is None:
        return
    try:
        hook(db, job, job.error_code, job.error_message or "")
        commit(db)
    except Exception:
        logger.exception("작업 %s 실패 후처리 오류", job.id)
        rollback(db)


def _fail(
    db: Session,
    job_id: int,
    error_code: FailureCode | str | None,
    error_message: str,
) -> None:
    """미반영 변경을 되돌리고 failed로 commit한 뒤, 실패 후처리와 SSE를 순서대로 한다."""
    rollback(db)
    job = job_repo.update_job(
        db, job_id, status=JobStatus.FAILED, error_code=error_code, error_message=error_message
    )
    if job is None:
        raise RuntimeError(f"작업 {job_id}이 없습니다.")
    commit(db)
    _call_on_failure(db, job)
    job = job_repo.get_job(db, job_id)
    if job is None:
        raise RuntimeError(f"작업 {job_id}이 없습니다.")
    publish_job_event(job_summary(job))


def _start_followups(dream_id: int, followups: list[FollowUp]) -> None:
    """장면 저장이 commit된 뒤에 다음 작업 행을 만들고 실행한다."""
    if not followups:
        return
    with session_factory() as db:
        queued: list[tuple[int, dict]] = []
        try:
            for spec in followups:
                child = job_repo.create_job_or_get_active(db, dream_id, spec.job_type, spec.target_id)
                queued.append((child.id, spec.payload))
            commit(db)
        except Exception:
            rollback(db)
            raise
    for child_id, payload in queued:
        enqueue(child_id, payload)


def _complete(db: Session, job_id: int, result: dict) -> None:
    """성공 후처리와 succeeded를 한 트랜잭션으로 commit한 뒤, 다음 작업을 실행하고 SSE를 보낸다."""
    job = job_repo.get_job(db, job_id)
    if job is None:
        raise RuntimeError(f"작업 {job_id}이 없습니다.")
    hook = get_on_success(job.type)
    followups = hook(db, job, result) if hook is not None else None
    job = job_repo.update_job(db, job_id, status=JobStatus.SUCCEEDED)
    if job is None:
        raise RuntimeError(f"작업 {job_id}이 없습니다.")
    commit(db)
    try:
        _start_followups(job.dream_id, followups or [])
    except Exception:
        # succeeded는 이미 commit됐다. 여기서 실패로 바꾸면 저장된 장면과 작업 상태가 어긋난다
        logger.exception("작업 %s 후속 작업 등록 실패", job_id)
    publish_job_event(job_summary(job))


def _run(db: Session, job_id: int, payload: dict) -> None:
    # 재시도는 아래 루프에서 이어진다. claim은 처음 한 번만 해서 running인 재시도를 건너뛰지 않는다.
    claimed = repo_bridge.claim_job(db, job_id)
    commit(db)
    if not claimed:
        job = job_repo.get_job(db, job_id)
        logger.warning("작업 %s를 실행하지 않음 (상태: %s)", job_id, None if job is None else job.status)
        return
    job = job_repo.get_job(db, job_id)
    if job is None:
        logger.warning("작업 %s를 실행하지 않음 (상태: %s)", job_id, None)
        return
    handler = get_handler(job.type)
    if handler is None:
        logger.error("작업 %s: 등록된 처리 함수가 없습니다 (%s)", job_id, job.type)
        _fail(db, job_id, None, INTERNAL_ERROR_MESSAGE)
        return

    ctx = RunnerContext(db, job)
    max_attempts = settings.job_max_retries + 1
    attempt = job.attempt
    while True:
        attempt += 1
        _save(db, job_id, status=JobStatus.RUNNING, stage=None, attempt=attempt)
        try:
            result = handler(ctx, payload)
        except JobError as exc:
            rollback(db)
            retry = exc.retryable and exc.code != FailureCode.CONTENT_POLICY and attempt < max_attempts
            if retry:
                ctx.logger.warning(
                    "작업 %s 실패 %s, 재시도 (%s/%s): %s", job_id, exc.code, attempt, max_attempts, exc.message
                )
                time.sleep(settings.job_retry_delay_seconds)
                continue
            ctx.logger.warning("작업 %s 실패 %s (시도 %s회): %s", job_id, exc.code, attempt, exc.message)
            _fail(db, job_id, exc.code, exc.message)
            return
        except Exception:
            ctx.logger.exception("작업 %s 처리 중 예외 (시도 %s회)", job_id, attempt)
            _fail(db, job_id, None, INTERNAL_ERROR_MESSAGE)
            return
        if result is None:
            result = {}
        try:
            _complete(db, job_id, result)
        except JobError as exc:
            # 렌더·이미지 비용이 든 핸들러는 다시 실행하지 않는다. retryable이어도 최종 실패다.
            ctx.logger.warning("작업 %s 성공 후처리 실패 %s: %s", job_id, exc.code, exc.message)
            _fail(db, job_id, exc.code, exc.message)
        except Exception:
            ctx.logger.exception("작업 %s 성공 후처리 중 예외", job_id)
            _fail(db, job_id, None, INTERNAL_ERROR_MESSAGE)
        return


def recover_interrupted() -> int:
    """서버 시작 시 호출. 재시작으로 사라진 running·queued 작업을 INTERRUPTED로 실패 처리한다.

    두 mark 함수는 바꾼 개수만 돌려주므로, UPDATE 전에 대상 id를 조회한 뒤 실패 후처리를 부른다.
    """
    with session_factory() as db:
        pending_ids = repo_bridge.list_active_job_ids(db)
        try:
            count = job_repo.mark_interrupted(db) + repo_bridge.mark_queued_interrupted(db)
            commit(db)
        except Exception:
            rollback(db)
            raise
        for job_id in pending_ids:
            job = job_repo.get_job(db, job_id)
            if job is None:
                continue
            _call_on_failure(db, job)
    if count:
        logger.warning("중단된 작업 %s개를 INTERRUPTED로 처리했습니다.", count)
    return count
