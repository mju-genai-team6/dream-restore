"""후처리 등록. DB 없이 데코레이터만 확인한다.

첫 등록은 monkeypatch.setitem으로 끼운다. 테스트가 끝나면 그 전 값(없으면 키 삭제)으로 돌아간다.
두 번째 등록은 데코레이터로 해서, 이미 있으면 거절하는지·register는 덮어쓰는지 확인한다.
"""
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


def test_hooks_reject_a_second_registration(monkeypatch):
    def ok(db, job, result):
        return None

    def failed(db, job, error_code, error_message):
        return None

    monkeypatch.setitem(ON_SUCCESS, JobType.GENERATE_NARRATION, ok)
    monkeypatch.setitem(ON_FAILURE, JobType.REVISE_SCENE, failed)

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


def test_register_still_overwrites(monkeypatch):
    def first(ctx, payload):
        return {}

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_NARRATION, first)

    @register(JobType.GENERATE_NARRATION)
    def second(ctx, payload):
        return {}

    assert get_handler(JobType.GENERATE_NARRATION) is second
