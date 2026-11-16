# TODO(DB 담당): repositories로 교체 (my-docs/requests.md 요청: mark_interrupted의 queued 처리)
"""repositories에 아직 없는 함수를 요청한 이름·시그니처 그대로 실제 DB 세션으로 구현한다.

모델 직접 사용은 이 파일 안에서만 허용한다. repositories 약속과 같게 commit하지 않고 flush까지만 한다.
"""
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.enums import FailureCode, JobStatus
from app.models import Job

QUEUED_INTERRUPTED_MESSAGE = "서버가 다시 시작되어 작업이 중단되었습니다. 다시 시도해 주세요."


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
