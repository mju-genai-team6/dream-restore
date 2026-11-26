"""작업 실행기.

- 작업 상태는 jobs 테이블에 저장한다. 요청 세션은 응답 뒤 닫히므로 작업마다 새 세션을 연다.
- 같은 꿈에 같은 종류의 작업이 진행 중이면 기존 jobId 반환 (jobs/submit.py, create_job_or_get_active)
- JobError(retryable=True)는 작업 종류별 재시도 횟수(_max_retries)까지 자동 재시도. CONTENT_POLICY는 바로 실패
- generate_image는 E2 핸들러가 안에서 재시도하므로 실행기 재시도는 0회 (MAX_RETRIES_BY_TYPE)
- generate_narration의 실행기 재시도는 1회 (MAX_RETRIES_BY_TYPE)
- JobError가 아닌 예외는 재시도 없이 실패. error_code는 NULL(API에서 INTERNAL_ERROR)
- 성공 후처리(on_success)와 succeeded는 같은 세션에서 한 번에 commit한다. 후처리가 실패하면 핸들러는 다시 실행하지 않는다
- 후처리가 돌려준 다음 작업의 행(queued)도 같은 트랜잭션에서 만든다. commit 뒤에는 enqueue로 실행만 한다.
  요청의 BackgroundTasks는 쓰지 않는다
- on_failure는 최종 실패와 서버 시작 시 INTERRUPTED에서만 호출한다. 재시도 중간에는 호출하지 않는다
- 실패 후처리가 예외를 내도 실행기는 멈추지 않는다. 작업은 그 전에 failed로 commit되어 있다.
  새 세션에서 작업 종류별 최소 대비책(FAILURE_FALLBACKS)을 실행하고, 그것도 실패하면 로그만 남긴다
- 시작 시 claim_job으로 queued를 running으로 한 번만 가져간다. 못 가져가면 핸들러·이벤트·후처리 없이 끝낸다
- 재시도는 이미 가져온 작업의 루프 안에서 이어지므로 claim_job을 다시 부르지 않는다
- publish_job_event는 commit 뒤에 부른다
- 서버 재시작 시 running·queued 작업은 INTERRUPTED로 실패 처리 (recover_interrupted)
- generate_image는 image_slots(settings.image_max_concurrency개)를 얻은 뒤에 claim한다. 기다리는 동안 queued
- 로그: 시작·성공은 INFO, error_code가 있는 실패는 WARNING 한 줄(원인 예외 종류 사슬과 앞 200자),
  INTERNAL_ERROR는 traceback. 원인 예외 내용은 DB error_message와 API 응답에 넣지 않는다
"""
import contextlib
import logging
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

# 작업 함수 등록(@register). worker가 registry를 import하므로 registry가 아니라 여기서 불러온다
import app.jobs.handlers.images
import app.jobs.handlers.narration
import app.jobs.handlers.scenes  # noqa: F401
import worker.image_gen.generate
import worker.render.handler
from app.core.config import settings
from app.core.enums import FailureCode, JobStage, JobStatus, JobType
from app.core.logs import exception_chain, next_cause, short_message
from app.db.session import SessionLocal
from app.jobs.context import JobError
from app.jobs.registry import FollowUp, get_handler, get_on_failure, get_on_success
from app.models import Job
from app.repositories import jobs as job_repo
from app.repositories import scenes as scene_repo
from app.schemas.jobs import INTERNAL_ERROR
from app.services.events import publish_job_event
from app.services.job_views import job_summary
from app.services.transactions import commit, rollback
from app.storage import paths

logger = logging.getLogger(__name__)

# 나레이션(TTS)은 선택 기능이다. mutagen이 없으면 ImportError만 남기고 등록을 건너뛴다.
# 서버는 계속 뜬다. 이미지 생성(worker.image_gen)과 렌더링(worker.render.handler)은 필수라 감싸지 않는다.
try:
    import worker.render.narration  # noqa: F401
except ImportError as exc:
    logger.error("나레이션(TTS) 핸들러를 등록하지 못함: %s", exc)

INTERNAL_ERROR_MESSAGE = "처리 중 오류가 발생했습니다. 다시 시도해 주세요."
# INTERNAL_ERROR 실패는 except 블록에서 logger.exception으로 traceback 전체를 남긴다
_UNEXPECTED_FAILURE = "작업 실패 %s status=failed error_code=%s step=%s attempt=%s elapsed_ms=%s"

# 테스트에서 테스트 DB 세션으로 바꿔 끼운다
session_factory = SessionLocal

# 작업 종류별 실행기 재시도 횟수. 없으면 settings.job_max_retries.
# generate_image는 E2가 안에서 최대 2회 재시도하므로, 실행기도 재시도하면 장면당 API 호출이 9번까지 늘어난다.
# generate_narration은 실행기 재시도 1회다. E2 핸들러 안의 TTS 재시도와는 별개다.
MAX_RETRIES_BY_TYPE: dict[JobType, int] = {
    JobType.GENERATE_IMAGE: 0,
    JobType.GENERATE_NARRATION: 1,
}

# 외부 이미지 API 동시 요청 수 제한. 테스트에서 바꿔 끼운다
image_slots = threading.BoundedSemaphore(settings.image_max_concurrency)

_PATH_KINDS = {
    "scene_original": paths.scene_original,
    "scene_blur": paths.scene_blur,
    "scene_narration": paths.scene_narration,
    "render_video": paths.render_video,
}


def _mark_scene_version_failed(db: Session, target_id: int | None) -> None:
    if target_id is not None:
        scene_repo.mark_scene_version_failed(db, target_id)


# on_failure가 예외를 냈을 때 새 세션에서 실행하는 최소 대비책. fn(db, target_id), commit은 실행기가 한다.
# generate_image는 장면 버전이 queued로 남으면 화면이 진행 중으로 보고 다시 만들기 버튼을 숨긴다
FAILURE_FALLBACKS: dict[JobType, Callable[[Session, int | None], None]] = {
    JobType.GENERATE_IMAGE: _mark_scene_version_failed,
}


def _job_fields(job_id: int, job_type: str, dream_id: int) -> str:
    return f"job_id={job_id} type={job_type} dream_id={dream_id}"


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


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


def _max_retries(job_type: JobType | str) -> int:
    return MAX_RETRIES_BY_TYPE.get(JobType(job_type), settings.job_max_retries)


def _slot_for(job_id: int) -> contextlib.AbstractContextManager:
    """generate_image면 image_slots를, 아니면 아무것도 잡지 않는 컨텍스트를 돌려준다.

    작업 종류만 짧은 세션으로 읽고 닫는다. 슬롯을 기다리는 동안 DB 연결을 잡지 않는다.
    """
    with session_factory() as db:
        job = job_repo.get_job(db, job_id)
        job_type = None if job is None else job.type
    if job_type == JobType.GENERATE_IMAGE:
        return image_slots
    return contextlib.nullcontext()


def run_job(job_id: int, payload: dict) -> None:
    try:
        slot = _slot_for(job_id)
    except Exception:
        logger.exception("작업 종류 조회 실패 job_id=%s", job_id)
        slot = contextlib.nullcontext()
    with slot, session_factory() as db:
        try:
            _run(db, job_id, payload)
        except Exception:
            logger.exception("작업 실행기 오류 job_id=%s error_code=%s", job_id, INTERNAL_ERROR)
            rollback(db)
            _fail_after_runner_error(db, job_id)
        finally:
            shutil.rmtree(settings.storage_path / paths.job_tmp(job_id), ignore_errors=True)


def _fail_after_runner_error(db: Session, job_id: int) -> None:
    try:
        _fail(db, job_id, None, INTERNAL_ERROR_MESSAGE)
    except Exception:
        logger.exception("작업 실패 기록 실패 job_id=%s", job_id)
        rollback(db)


def _call_on_failure(db: Session, job: Job) -> None:
    """실패가 commit된 뒤에 부른다. 후처리 예외는 로그로 남기고 대비책을 실행한 뒤 계속한다.

    rollback하면 job의 속성이 만료되므로 필요한 값은 후처리 전에 읽어 둔다.
    """
    hook = get_on_failure(job.type)
    if hook is None:
        return
    job_type, target_id = JobType(job.type), job.target_id
    fields = _job_fields(job.id, job_type, job.dream_id)
    try:
        hook(db, job, job.error_code, job.error_message or "")
        commit(db)
    except Exception:
        logger.exception("작업 실패 후처리 오류 %s target_id=%s", fields, target_id)
        rollback(db)
        _run_failure_fallback(job_type, target_id, fields)


def _run_failure_fallback(job_type: JobType, target_id: int | None, fields: str) -> None:
    fallback = FAILURE_FALLBACKS.get(job_type)
    if fallback is None:
        return
    try:
        with session_factory() as db:
            fallback(db, target_id)
            commit(db)
    except Exception:
        logger.exception("작업 실패 후처리 대비책도 실패 %s target_id=%s", fields, target_id)
        return
    logger.warning("작업 실패 후처리 대비책 실행 %s target_id=%s", fields, target_id)


def _fail(
    db: Session,
    job_id: int,
    error_code: FailureCode | str | None,
    error_message: str,
) -> None:
    """미반영 변경을 되돌리고 failed로 commit한 뒤, 실패 후처리와 publish_job_event를 순서대로 한다."""
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


def _create_followups(db: Session, dream_id: int, followups: list[FollowUp]) -> list[tuple[int, dict]]:
    """다음 작업 행(queued)을 호출한 쪽의 트랜잭션 안에서 만든다. commit하지 않는다."""
    queued: list[tuple[int, dict]] = []
    for spec in followups:
        child = job_repo.create_job_or_get_active(db, dream_id, spec.job_type, spec.target_id)
        queued.append((child.id, spec.payload))
    return queued


def _complete(db: Session, job_id: int, result: dict) -> None:
    """성공 후처리, 다음 작업 행, succeeded를 한 트랜잭션으로 commit한 뒤 다음 작업을 실행하고 publish_job_event를 부른다.

    commit 직후 서버가 꺼져도 다음 작업 행은 queued로 남아, 재시작 때 INTERRUPTED로 처리된다.
    """
    job = job_repo.get_job(db, job_id)
    if job is None:
        raise RuntimeError(f"작업 {job_id}이 없습니다.")
    hook = get_on_success(job.type)
    followups = hook(db, job, result) if hook is not None else None
    queued = _create_followups(db, job.dream_id, followups or [])
    job = job_repo.update_job(db, job_id, status=JobStatus.SUCCEEDED)
    if job is None:
        raise RuntimeError(f"작업 {job_id}이 없습니다.")
    commit(db)
    for child_id, payload in queued:
        try:
            enqueue(child_id, payload)
        except Exception:
            # 행은 이미 commit됐다. queued로 남은 작업은 재시작 때 INTERRUPTED가 되어 다시 요청할 수 있다
            logger.exception("다음 작업 실행 실패 job_id=%s next_job_id=%s", job_id, child_id)
    publish_job_event(job_summary(job))


def _run(db: Session, job_id: int, payload: dict) -> None:
    # 재시도는 아래 루프에서 이어진다. claim은 처음 한 번만 해서 running인 재시도를 건너뛰지 않는다.
    claimed = job_repo.claim_job(db, job_id)
    commit(db)
    if not claimed:
        job = job_repo.get_job(db, job_id)
        logger.warning("작업을 실행하지 않음 job_id=%s status=%s", job_id, None if job is None else job.status)
        return
    job = job_repo.get_job(db, job_id)
    if job is None:
        logger.warning("작업을 실행하지 않음 job_id=%s status=%s", job_id, None)
        return
    started = time.monotonic()
    fields = _job_fields(job.id, job.type, job.dream_id)
    logger.info("작업 시작 %s target_id=%s", fields, job.target_id)
    handler = get_handler(job.type)
    if handler is None:
        logger.error(
            "작업 실패 %s status=failed error_code=%s elapsed_ms=%s: 등록된 처리 함수가 없습니다",
            fields, INTERNAL_ERROR, _elapsed_ms(started),
        )
        _fail(db, job_id, None, INTERNAL_ERROR_MESSAGE)
        return

    ctx = RunnerContext(db, job)
    max_attempts = _max_retries(job.type) + 1
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
            _log_expected_failure(fields, exc, "handler", attempt, started)
            _fail(db, job_id, exc.code, exc.message)
            return
        except Exception:
            logger.exception(_UNEXPECTED_FAILURE, fields, INTERNAL_ERROR, "handler", attempt, _elapsed_ms(started))
            _fail(db, job_id, None, INTERNAL_ERROR_MESSAGE)
            return
        if result is None:
            result = {}
        try:
            _complete(db, job_id, result)
        except JobError as exc:
            # 렌더·이미지 비용이 든 핸들러는 다시 실행하지 않는다. retryable이어도 최종 실패다.
            _log_expected_failure(fields, exc, "on_success", attempt, started)
            _fail(db, job_id, exc.code, exc.message)
        except Exception:
            logger.exception(_UNEXPECTED_FAILURE, fields, INTERNAL_ERROR, "on_success", attempt, _elapsed_ms(started))
            _fail(db, job_id, None, INTERNAL_ERROR_MESSAGE)
        else:
            logger.info("작업 성공 %s status=succeeded attempt=%s elapsed_ms=%s", fields, attempt, _elapsed_ms(started))
        return


def _log_expected_failure(fields: str, exc: JobError, step: str, attempt: int, started: float) -> None:
    """원인 예외는 로그에만 남긴다. DB error_message와 API 응답은 exc.message(사용자용 문구) 그대로다."""
    cause = next_cause(exc)
    logger.warning(
        "작업 실패 %s status=failed error_code=%s step=%s attempt=%s elapsed_ms=%s cause=%s message=%s",
        fields,
        exc.code,
        step,
        attempt,
        _elapsed_ms(started),
        "-" if cause is None else exception_chain(cause),
        short_message(exc if cause is None else cause),
    )


def recover_interrupted() -> int:
    """서버 시작 시 호출. 재시작으로 사라진 running·queued 작업을 INTERRUPTED로 실패 처리한다.

    두 mark 함수는 바꾼 개수만 돌려주므로, UPDATE 전에 대상 id를 조회한 뒤 실패 후처리를 부른다.
    """
    with session_factory() as db:
        pending_ids = job_repo.list_active_job_ids(db)
        try:
            count = job_repo.mark_interrupted(db) + job_repo.mark_queued_interrupted(db)
            commit(db)
        except Exception:
            rollback(db)
            raise
        for job_id in pending_ids:
            job = job_repo.get_job(db, job_id)
            if job is None:
                continue
            logger.warning(
                "작업 중단 처리 %s target_id=%s status=failed error_code=%s",
                _job_fields(job.id, job.type, job.dream_id), job.target_id, job.error_code,
            )
            _call_on_failure(db, job)
    if count:
        logger.warning("중단된 작업 %s개를 INTERRUPTED로 처리했습니다.", count)
    return count
