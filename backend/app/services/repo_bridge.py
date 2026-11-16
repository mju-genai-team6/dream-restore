# TODO(DB 담당): repositories로 교체 (my-docs/requests.md 요청: update_raw_text, get_latest_extraction,
# get_active_jobs, mark_interrupted의 queued 처리)
"""repositories에 아직 없는 함수를 요청한 이름·시그니처 그대로 실제 DB 세션으로 구현한다.

모델 직접 사용은 이 파일 안에서만 허용한다. repositories 약속과 같게 commit하지 않고 flush까지만 한다.
"""
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.enums import FailureCode, JobStatus
from app.models import Dream, Extraction, Job
from app.models.job import ACTIVE_JOB_STATUSES

QUEUED_INTERRUPTED_MESSAGE = "서버가 다시 시작되어 작업이 중단되었습니다. 다시 시도해 주세요."


def update_raw_text(db: Session, dream_id: int, raw_text: str) -> Dream | None:
    """STT 변환 텍스트를 raw_text에 저장한다. 꿈 기록이 없으면 None."""
    dream = db.get(Dream, dream_id)
    if dream is None:
        return None
    dream.raw_text = raw_text
    db.flush()
    return dream


def get_latest_extraction(db: Session, dream_id: int) -> Extraction | None:
    """가장 최근 추출 1행. 없으면 None. 순서는 repositories.extractions.list_elements와 같다."""
    return db.scalar(
        select(Extraction)
        .where(Extraction.dream_id == dream_id)
        .order_by(Extraction.created_at.desc(), Extraction.id.desc())
        .limit(1)
    )


def get_active_jobs(db: Session, dream_id: int) -> list[Job]:
    """꿈의 진행 중(queued·running) 작업 전부. 종류와 상관없이 최신순."""
    return list(
        db.scalars(
            select(Job)
            .where(Job.dream_id == dream_id, Job.status.in_(ACTIVE_JOB_STATUSES))
            .order_by(Job.created_at.desc(), Job.id.desc())
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
