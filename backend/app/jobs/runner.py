"""작업 실행기.

- 작업 상태는 jobs 테이블에 저장한다. 요청 세션은 응답 뒤 닫히므로 작업마다 새 세션을 연다.
- 같은 꿈에 같은 종류의 작업이 진행 중이면 기존 jobId 반환 (services/jobs.py, create_job_or_get_active)
- JobError(retryable=True)는 settings.job_max_retries회까지 자동 재시도. CONTENT_POLICY는 바로 실패
- JobError가 아닌 예외는 재시도 없이 실패. error_code는 NULL(API에서 INTERNAL_ERROR)
- 서버 재시작 시 running·queued 작업은 INTERRUPTED로 실패 처리 (recover_interrupted)
- 이미지 생성 동시 요청 수는 settings.image_max_concurrency로 제한 (C-S3-02)
"""
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

# 작업 함수 등록(@register). worker가 registry를 import하므로 registry가 아니라 여기서 불러온다
import worker.image_gen.generate
import worker.render.handler  # noqa: F401
from app.core.config import settings
from app.core.enums import FailureCode, JobStage, JobStatus
from app.db.session import SessionLocal
from app.jobs.context import JobError
from app.jobs.registry import get_handler
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
        _save(db, job_id, status=JobStatus.FAILED, error_code=None, error_message=INTERNAL_ERROR_MESSAGE)
    except Exception:
        logger.exception("작업 %s 실패 기록 실패", job_id)
        rollback(db)


def _run(db: Session, job_id: int, payload: dict) -> None:
    job = job_repo.get_job(db, job_id)
    if job is None or job.status != JobStatus.QUEUED:
        logger.warning("작업 %s를 실행하지 않음 (상태: %s)", job_id, None if job is None else job.status)
        return
    handler = get_handler(job.type)
    if handler is None:
        logger.error("작업 %s: 등록된 처리 함수가 없습니다 (%s)", job_id, job.type)
        _save(db, job_id, status=JobStatus.FAILED, error_code=None, error_message=INTERNAL_ERROR_MESSAGE)
        return

    ctx = RunnerContext(db, job)
    max_attempts = settings.job_max_retries + 1
    attempt = job.attempt
    while True:
        attempt += 1
        _save(db, job_id, status=JobStatus.RUNNING, stage=None, attempt=attempt)
        try:
            handler(ctx, payload)
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
            _save(db, job_id, status=JobStatus.FAILED, error_code=exc.code, error_message=exc.message)
            return
        except Exception:
            ctx.logger.exception("작업 %s 처리 중 예외 (시도 %s회)", job_id, attempt)
            rollback(db)
            _save(db, job_id, status=JobStatus.FAILED, error_code=None, error_message=INTERNAL_ERROR_MESSAGE)
            return
        _save(db, job_id, status=JobStatus.SUCCEEDED)
        return


def recover_interrupted() -> int:
    """서버 시작 시 호출. 재시작으로 사라진 running·queued 작업을 INTERRUPTED로 실패 처리한다."""
    with session_factory() as db:
        try:
            count = job_repo.mark_interrupted(db) + repo_bridge.mark_queued_interrupted(db)
            commit(db)
        except Exception:
            rollback(db)
            raise
    if count:
        logger.warning("중단된 작업 %s개를 INTERRUPTED로 처리했습니다.", count)
    return count
