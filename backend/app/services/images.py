"""실패한 장면 이미지 다시 생성 POST /dreams/{id}/images/retry (C-S3-02)."""
import logging

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import DreamStatus, JobType
from app.core.errors import InvalidState
from app.jobs.handlers.images import image_payload
from app.jobs.submit import submit_job
from app.repositories import jobs as job_repo
from app.repositories import scenes as scene_repo
from app.schemas.jobs import JobSummary
from app.services.interview import require_dream
from app.services.job_views import job_summary
from app.services.llm_calls import dream_lock
from app.services.transactions import expire_loaded
from app.storage import paths

logger = logging.getLogger(__name__)


def retry_images(db: Session, dream_id: int, background_tasks: BackgroundTasks) -> list[JobSummary]:
    """이미지가 없는 현재 장면 버전마다 generate_image 작업을 돌려준다.

    진행 중 작업이 있는 장면은 그 작업을 그대로 돌려주고, 없는 장면만 새로 등록한다.
    그래서 같은 요청을 다시 보내면 같은 작업 목록이 나온다. 이미지 결과는 비어 있으므로 같은 장면 버전을 다시 쓴다.
    """
    with dream_lock(dream_id):
        expire_loaded(db)
        dream = require_dream(db, dream_id)
        if DreamStatus(dream.status) != DreamStatus.SCENES_READY:
            raise InvalidState("이미지를 다시 만들 수 있는 단계가 아닙니다.", {"status": dream.status})
        active = {
            job.target_id: job
            for job in job_repo.get_active_jobs(db, dream_id)
            if job.type == JobType.GENERATE_IMAGE
        }
        summaries: list[JobSummary] = []
        for scene in scene_repo.list_scenes(db, dream_id):
            version = scene.current_version
            if version is None or version.image_path is not None:
                continue
            if version.id in active:
                summaries.append(job_summary(active[version.id]))
                continue
            scene_repo.reset_failed_scene_version(db, version.id)
            # DB에는 이미지가 없는데 파일만 남았으면(후처리 실패, commit 전 종료) E2가 덮어쓰기를 거절한다
            leftover = settings.storage_path / paths.scene_original(dream_id, scene.id, version.version_no)
            leftover.unlink(missing_ok=True)
            characters = scene_repo.list_scene_characters(db, version.id)
            if characters is None:
                logger.warning("장면 %s 버전 %s가 없어 이미지 작업을 다시 등록하지 않습니다.", scene.id, version.id)
                continue
            job, _created = submit_job(
                db,
                background_tasks,
                dream_id=dream_id,
                job_type=JobType.GENERATE_IMAGE,
                target_id=version.id,
                payload=image_payload(scene.id, version.version_no, version.prompt_en, characters),
            )
            summaries.append(job_summary(job))
    return summaries
