"""generate_narration 후처리. 음성 파일은 E2 핸들러가 저장하고, 여기서는 꿈 상태만 본다.

성공과 실패 모두 같은 조건으로 images_ready를 확인한다. 나레이션 실패는 꿈 흐름을 막지 않는다.
"""
from sqlalchemy.orm import Session

from app.core.enums import JobType
from app.jobs.handlers.images import maybe_mark_images_ready
from app.jobs.registry import on_failure, on_success
from app.models.job import Job
from app.models.scene import SceneVersion

# E2 tts_max_chars 기본값과 같다. 넘으면 핸들러가 INVALID_INPUT으로 거절한다.
NARRATION_TEXT_MAX = 200


def narration_text(summary: str) -> str | None:
    """E2와 같이 공백을 접는다. 비면 None, 길면 NARRATION_TEXT_MAX자로 자른다."""
    text = " ".join(summary.split())
    if not text:
        return None
    return text[:NARRATION_TEXT_MAX]


def narration_payload(version: SceneVersion) -> dict | None:
    """E2 handle_generate_narration 입력. voice는 생략해 설정의 기본 음성을 쓴다."""
    text = narration_text(version.summary_ko)
    if text is None:
        return None
    return {"scene_id": version.scene_id, "version_no": version.version_no, "text": text}


@on_success(JobType.GENERATE_NARRATION)
def narration_finished(db: Session, job: Job, result: dict) -> None:
    """실행기가 이 함수 뒤에 succeeded와 함께 commit한다. 여기서 commit하지 않는다.

    현재 작업은 아직 running이다. 조건 확인이 이 작업 id를 진행 중에서 뺀다.
    """
    maybe_mark_images_ready(db, job.dream_id, ignore_job_id=job.id)


@on_failure(JobType.GENERATE_NARRATION)
def narration_failed(db: Session, job: Job, error_code: str | None, error_message: str) -> None:
    """실패가 commit된 뒤에 부른다. 조건이 맞으면 images_ready로 간다."""
    maybe_mark_images_ready(db, job.dream_id, ignore_job_id=job.id)
