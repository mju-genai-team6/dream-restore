"""후처리 등록. DB 없이 데코레이터만 확인한다."""
import pytest

from app.core.enums import JobType
from app.jobs.registry import (
    HANDLERS,
    ON_FAILURE,
    ON_SUCCESS,
    get_handler,
    get_on_failure,
    get_on_success,
    on_failure,
    on_success,
    register,
)


def test_hooks_reject_a_second_registration():
    @on_success(JobType.GENERATE_NARRATION)
    def ok(db, job, result):
        return None

    @on_failure(JobType.REVISE_SCENE)
    def failed(db, job, error_code, error_message):
        return None

    try:
        assert get_on_success(JobType.GENERATE_NARRATION) is ok
        assert get_on_failure(JobType.REVISE_SCENE) is failed
        with pytest.raises(RuntimeError, match="on_success"):
            @on_success(JobType.GENERATE_NARRATION)
            def _again(db, job, result):
                return None

        with pytest.raises(RuntimeError, match="on_failure"):
            @on_failure(JobType.REVISE_SCENE)
            def _again_failed(db, job, error_code, error_message):
                return None

        assert ON_SUCCESS[JobType.GENERATE_NARRATION] is ok
        assert ON_FAILURE[JobType.REVISE_SCENE] is failed
    finally:
        ON_SUCCESS.pop(JobType.GENERATE_NARRATION, None)
        ON_FAILURE.pop(JobType.REVISE_SCENE, None)


def test_register_still_overwrites():
    @register(JobType.GENERATE_NARRATION)
    def first(ctx, payload):
        return {}

    @register(JobType.GENERATE_NARRATION)
    def second(ctx, payload):
        return {}

    try:
        assert get_handler(JobType.GENERATE_NARRATION) is second
    finally:
        HANDLERS.pop(JobType.GENERATE_NARRATION, None)
