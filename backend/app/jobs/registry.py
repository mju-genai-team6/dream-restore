"""작업 종류별 처리 함수 등록."""
from collections.abc import Callable

from app.core.enums import JobType
from app.jobs.context import JobContext

Handler = Callable[[JobContext, dict], dict]

HANDLERS: dict[JobType, Handler] = {}


def register(job_type: JobType):
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn
    return deco
