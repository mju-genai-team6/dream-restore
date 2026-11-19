# TODO(DB 담당): repositories로 교체 (my-docs/requests.md: claim_job, mark_interrupted의 queued·id 목록,
#   장면 버전 이미지 결과·상태 함수, lock_dream)
"""repositories에 아직 없는 함수를 요청한 이름·시그니처 그대로 실제 DB 세션으로 구현한다.

모델 직접 사용은 이 파일 안에서만 허용한다. repositories 약속과 같게 commit하지 않고 flush까지만 한다.
"""
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.enums import FailureCode, JobStatus
from app.models import Dream, SceneVersion
from app.models.job import ACTIVE_JOB_STATUSES, Job

QUEUED_INTERRUPTED_MESSAGE = "서버가 다시 시작되어 작업이 중단되었습니다. 다시 시도해 주세요."


# TODO(DB 담당): repositories.claim_job 으로 교체
def claim_job(db: Session, job_id: int) -> bool:
    """queued인 작업을 running으로 바꾼다. 바뀐 행이 있으면 True.

    started_at은 이 변경에서 기록한다. 동시에 두 실행기가 같은 작업을 시작해도 한 쪽만 True다.
    commit은 호출하는 쪽이 한다.
    """
    result = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.QUEUED.value)
        .values(status=JobStatus.RUNNING.value, started_at=func.now())
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


def list_active_job_ids(db: Session) -> list[int]:
    """서버 재시작 처리 전에 호출. queued·running 작업 id를 만든 순서대로 돌려준다.

    mark_interrupted와 mark_queued_interrupted는 바꾼 개수만 돌려준다.
    실패 후처리를 부를 대상은 그 UPDATE 전에 여기서 조회한다.
    """
    return list(
        db.scalars(
            select(Job.id).where(Job.status.in_(ACTIVE_JOB_STATUSES)).order_by(Job.created_at, Job.id)
        )
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


# TODO(DB 담당): repositories.dreams.lock_dream 으로 교체
def lock_dream(db: Session, dream_id: int) -> Dream | None:
    """꿈 행을 SELECT ... FOR UPDATE로 잠근다. 트랜잭션이 끝날 때까지 다른 잠금 요청은 기다린다.

    같은 꿈의 이미지 작업 후처리가 동시에 끝날 때, 앞 작업이 commit한 뒤에 all_images_done을 읽게 한다.
    """
    return db.scalar(
        select(Dream).where(Dream.id == dream_id).with_for_update().execution_options(populate_existing=True)
    )


# TODO(DB 담당): repositories.scenes.save_image_result 로 교체
def save_image_result(
    db: Session,
    scene_version_id: int,
    *,
    final_prompt: str,
    model: str,
    settings: dict,
    seed: int | None,
    image_path: str,
    generated_at: datetime,
    confidence_level: str | None,
) -> bool:
    """이미지 생성 결과와 장면 확신도를 한 번에 저장하고 status를 succeeded로 바꾼다.

    image_path가 비어 있는 버전만 바꾼다(결과는 한 번만 채움). 바뀐 행이 있으면 True.
    confidence_level이 이미 있으면 그 값은 그대로 둔다.
    """
    values: dict = {
        "final_prompt": final_prompt,
        "model": model,
        "settings": settings,
        "seed": seed,
        "image_path": image_path,
        "generated_at": generated_at,
        "status": JobStatus.SUCCEEDED.value,
    }
    if confidence_level is not None:
        values["confidence_level"] = func.coalesce(SceneVersion.confidence_level, confidence_level)
    result = db.execute(
        update(SceneVersion)
        .where(SceneVersion.id == scene_version_id, SceneVersion.image_path.is_(None))
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


# TODO(DB 담당): repositories.scenes.mark_scene_version_failed 로 교체
def mark_scene_version_failed(db: Session, scene_version_id: int) -> bool:
    """이미지가 없고 succeeded가 아닌 장면 버전을 failed로 바꾼다. 바뀐 행이 있으면 True."""
    result = db.execute(
        update(SceneVersion)
        .where(
            SceneVersion.id == scene_version_id,
            SceneVersion.image_path.is_(None),
            SceneVersion.status != JobStatus.SUCCEEDED.value,
        )
        .values(status=JobStatus.FAILED.value)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


# TODO(DB 담당): repositories.scenes.reset_failed_scene_version 으로 교체
def reset_failed_scene_version(db: Session, scene_version_id: int) -> bool:
    """이미지 다시 생성 전에 failed인 장면 버전을 queued로 되돌린다. 바뀐 행이 있으면 True."""
    result = db.execute(
        update(SceneVersion)
        .where(
            SceneVersion.id == scene_version_id,
            SceneVersion.image_path.is_(None),
            SceneVersion.status == JobStatus.FAILED.value,
        )
        .values(status=JobStatus.QUEUED.value)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1
