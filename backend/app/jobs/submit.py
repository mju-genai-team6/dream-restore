"""작업 생성과 실행 예약.

registry에 두지 않는다. worker가 registry를 import하고 runner가 worker를 import하므로,
schedule이 필요한 함수를 registry에 두면 registry → runner → worker → registry 순환이 된다.
runner에도 두지 않는다. runner는 import만으로 이미지·렌더 워커를 불러오고, 이 모듈은 그 모듈을 부르지 않는다.
"""
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.enums import JobType
from app.jobs import runner
from app.models.job import Job
from app.repositories import jobs as job_repo
from app.services.events import publish_job_event
from app.services.job_views import job_summary
from app.services.transactions import commit, rollback


def submit_job(
    db: Session,
    background_tasks: BackgroundTasks,
    *,
    dream_id: int,
    job_type: JobType | str,
    target_id: int | None,
    payload: dict | None = None,
) -> tuple[Job, bool]:
    """작업을 만들거나 진행 중 작업을 돌려주고, 새 작업만 실행기에 넘긴다.

    같은 꿈·종류·target_id의 queued·running 작업이 있으면 그 작업을 돌려주고 실행은 예약하지 않는다.
    반환 bool은 호출 전에 진행 중 목록에 없던 작업인지다. 두 요청이 동시에 들어오면 그 목록이
    둘 다 비어 있어 created가 둘 다 True일 수 있고, 같은 작업의 실행이 두 번 예약될 수 있다.
    실행기는 claim_job으로 queued일 때만 작업을 가져가므로 핸들러는 한 번만 실행된다.

    예:
        job, created = submit_job(
            db, background_tasks,
            dream_id=dream_id, job_type=JobType.RENDER_VIDEO,
            target_id=render_id, payload={"render_id": render_id},
        )
    """
    active_ids = {row.id for row in job_repo.get_active_jobs(db, dream_id)}
    try:
        job = job_repo.create_job_or_get_active(db, dream_id, job_type, target_id)
        commit(db)
    except Exception:
        rollback(db)
        raise
    created = job.id not in active_ids
    if created:
        publish_job_event(job_summary(job))
        runner.schedule(background_tasks, job.id, payload or {})
    return job, created
