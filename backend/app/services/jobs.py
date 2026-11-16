"""장면 생성 작업 등록·작업 조회."""
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.enums import DreamStatus, ExtractionPhase, JobType
from app.core.errors import InvalidState, NotFound
from app.jobs import runner
from app.repositories import extractions as extraction_repo
from app.repositories import jobs as job_repo
from app.schemas.jobs import JobCreate, JobSummary
from app.services.events import publish_job_event
from app.services.interview import require_dream
from app.services.job_views import job_summary
from app.services.llm_calls import dream_lock
from app.services.transactions import commit, expire_loaded, rollback


def _ensure_scenes_requestable(db: Session, dream_id: int) -> None:
    dream = require_dream(db, dream_id)
    if DreamStatus(dream.status) != DreamStatus.INTERVIEWING:
        raise InvalidState("현재 단계에서는 장면을 만들 수 없습니다.", {"status": dream.status})
    latest = extraction_repo.get_latest_extraction(db, dream_id)
    if latest is None or latest.phase != ExtractionPhase.AFTER_INTERVIEW:
        raise InvalidState("요소 목록을 먼저 확인해 주세요.", {"status": dream.status})
    elements = extraction_repo.list_elements(db, dream_id)
    if not elements:
        raise InvalidState("장면을 만들 요소가 없습니다.", {"element_ids": []})
    missing = [row.id for row in elements if row.confidence is None]
    if missing:
        raise InvalidState("모든 요소의 확신도를 선택해 주세요.", {"element_ids": missing})


def create_job(
    db: Session, dream_id: int, body: JobCreate, background_tasks: BackgroundTasks
) -> JobSummary:
    """진행 중인 장면 생성 작업이 있으면 그 작업을 돌려준다. 새 작업일 때만 실행기에 넘긴다.

    확신도 저장과 같은 꿈별 잠금을 써서, 확인한 확신도가 작업 등록 전에 바뀌지 않게 한다.
    """
    with dream_lock(dream_id):
        # 잠금을 기다리는 동안 다른 요청이 상태를 바꿨을 수 있어 DB에서 다시 읽는다
        expire_loaded(db)
        _ensure_scenes_requestable(db, dream_id)
        active = {job.id for job in job_repo.get_active_jobs(db, dream_id)}
        try:
            job = job_repo.create_job_or_get_active(db, dream_id, JobType(body.type))
            commit(db)
        except Exception:
            rollback(db)
            raise
    summary = job_summary(job)
    if job.id not in active:
        publish_job_event(summary)
        runner.schedule(background_tasks, job.id)
    return summary


def get_job(db: Session, job_id: int) -> JobSummary:
    job = job_repo.get_job(db, job_id)
    if job is None:
        raise NotFound("작업을 찾을 수 없습니다.", {"job_id": job_id})
    return job_summary(job)
