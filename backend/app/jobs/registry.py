"""작업 종류별 처리 함수 등록."""
import time
from collections.abc import Callable

from app.core.enums import JobStage, JobType
from app.jobs.context import JobContext

Handler = Callable[[JobContext, dict], dict]

HANDLERS: dict[JobType, Handler] = {}

# 가짜 처리의 단계 사이 대기 (테스트에서 0으로 바꾼다)
FAKE_STAGE_SECONDS = 0.5


def register(job_type: JobType):
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn
    return deco


def get_handler(job_type: JobType | str) -> Handler | None:
    return HANDLERS.get(JobType(job_type))


# TODO(C-S3-01): D의 split_scenes와 DB 담당 create_scenes로 실제 장면 생성 연결 (완료 시 scenes_ready)
@register(JobType.GENERATE_SCENES)
def fake_generate_scenes(ctx: JobContext, payload: dict) -> dict:
    """단계만 보고하고 성공한다. 꿈 상태와 장면은 바꾸지 않는다."""
    ctx.report_stage(JobStage.SPLITTING)
    time.sleep(FAKE_STAGE_SECONDS)
    ctx.report_stage(JobStage.PROMPTING)
    time.sleep(FAKE_STAGE_SECONDS)
    return {}
