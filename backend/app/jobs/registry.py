"""작업 종류별 처리 함수와 후처리 등록."""
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import JobType
from app.jobs.context import JobContext
from app.models.job import Job


@dataclass(frozen=True)
class FollowUp:
    """성공 후처리가 돌려주는 다음 작업. 실행기가 같은 트랜잭션에서 queued 행을 만들고, commit 뒤에 실행한다."""

    job_type: JobType
    target_id: int | None
    payload: dict


Handler = Callable[[JobContext, dict], dict]
SuccessHook = Callable[[Session, Job, dict], list[FollowUp] | None]
FailureHook = Callable[[Session, Job, str | None, str], None]

HANDLERS: dict[JobType, Handler] = {}
ON_SUCCESS: dict[JobType, SuccessHook] = {}
ON_FAILURE: dict[JobType, FailureHook] = {}


def register(job_type: JobType):
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn
    return deco


def get_handler(job_type: JobType | str) -> Handler | None:
    return HANDLERS.get(JobType(job_type))


def on_success(job_type: JobType):
    """작업 종류당 성공 후처리 하나. 이미 있으면 서버가 뜨는 중(import)에 오류를 낸다.

    fn(db, job, result) -> list[FollowUp] | None. result는 핸들러 반환 dict.
    실행기가 부를 때 작업은 아직 running이고, succeeded와 같은 트랜잭션에서 commit된다.
    반환한 다음 작업은 같은 트랜잭션에서 queued 행으로 만들고, commit 뒤에 실행한다.
    """
    def deco(fn: SuccessHook) -> SuccessHook:
        key = JobType(job_type)
        if key in ON_SUCCESS:
            raise RuntimeError(f"on_success가 이미 등록되어 있습니다: {key.value}")
        ON_SUCCESS[key] = fn
        return fn
    return deco


def on_failure(job_type: JobType):
    """작업 종류당 실패 후처리 하나. 이미 있으면 서버가 뜨는 중(import)에 오류를 낸다.

    fn(db, job, error_code, error_message) -> None.
    최종 실패로 commit된 뒤에만 호출된다. 재시도 중간에는 호출되지 않는다.
    """
    def deco(fn: FailureHook) -> FailureHook:
        key = JobType(job_type)
        if key in ON_FAILURE:
            raise RuntimeError(f"on_failure가 이미 등록되어 있습니다: {key.value}")
        ON_FAILURE[key] = fn
        return fn
    return deco


def get_on_success(job_type: JobType | str) -> SuccessHook | None:
    return ON_SUCCESS.get(JobType(job_type))


def get_on_failure(job_type: JobType | str) -> FailureHook | None:
    return ON_FAILURE.get(JobType(job_type))
