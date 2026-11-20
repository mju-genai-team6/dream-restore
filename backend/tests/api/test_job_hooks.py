"""작업 성공·실패 후처리. 핸들러와 후처리는 테스트 안에서만 끼운다."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import FailureCode, JobStatus, JobType
from app.jobs import runner
from app.jobs.context import JobError
from app.jobs.registry import HANDLERS, ON_FAILURE, ON_SUCCESS
from app.jobs.submit import submit_job
from app.main import app
from app.models import Dream
from app.repositories import jobs as job_repo
from app.services.repo_bridge import QUEUED_INTERRUPTED_MESSAGE
from tests.api import rows

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}
RUNNING_INTERRUPTED_MESSAGE = "서버가 다시 시작되어 작업이 중단되었습니다."


def _dream() -> int:
    return client.post("/dreams", json=TEXT).json()["dream_id"]


def _confirmed(session_factory: sessionmaker[Session], dream_id: int) -> str | None:
    with session_factory() as db:
        dream = db.get(Dream, dream_id)
        assert dream is not None
        return dream.confirmed_text


def _job(
    session_factory: sessionmaker[Session],
    dream_id: int,
    type_: JobType = JobType.GENERATE_SCENES,
    target_id: int | None = None,
    *,
    status: JobStatus | None = None,
) -> int:
    with session_factory.begin() as db:
        job = job_repo.create_job_or_get_active(db, dream_id, type_, target_id)
        if status is not None:
            job_repo.update_job(db, job.id, status=status)
        return job.id


def test_on_success_commits_with_succeeded(monkeypatch, session_factory, read_db):
    dream_id = _dream()
    job_id = _job(session_factory, dream_id)
    original = _confirmed(session_factory, dream_id)
    started = threading.Event()
    release = threading.Event()
    seen: dict[str, tuple[str, str | None]] = {}

    def handle(ctx, payload):
        return {"ok": True}

    def on_success(db, job, result):
        assert job.status == JobStatus.RUNNING
        assert result == {"ok": True}
        dream = db.get(Dream, job.dream_id)
        assert dream is not None
        dream.confirmed_text = "from-hook"
        db.flush()
        started.set()
        assert release.wait(5)

    def observe():
        if not started.wait(5):
            return
        with session_factory() as db:
            row = job_repo.get_job(db, job_id)
            dream = db.get(Dream, dream_id)
            if row is None or dream is None:
                return
            seen["during"] = (row.status, dream.confirmed_text)
        release.set()

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)
    monkeypatch.setitem(ON_SUCCESS, JobType.GENERATE_SCENES, on_success)
    watcher = threading.Thread(target=observe)
    watcher.start()
    try:
        runner.run_job(job_id, {})
    finally:
        release.set()
        watcher.join(5)

    assert seen["during"] == (JobStatus.RUNNING, original)
    assert original != "from-hook"
    read_db.expire_all()
    dream = read_db.get(Dream, dream_id)
    [job] = rows.jobs(read_db)
    assert job.id == job_id
    assert job.status == JobStatus.SUCCEEDED
    assert dream is not None and dream.confirmed_text == "from-hook"


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (JobError(FailureCode.RENDER_FAILED, "합성 실패", retryable=True), "RENDER_FAILED", "합성 실패"),
        (RuntimeError("버그"), None, runner.INTERNAL_ERROR_MESSAGE),
    ],
)
def test_on_success_failure_rolls_back_and_does_not_rerun(
    monkeypatch, session_factory, read_db, error, code, message
):
    dream_id = _dream()
    job_id = _job(session_factory, dream_id)
    original = _confirmed(session_factory, dream_id)
    handler_calls: list[int] = []
    failure_calls: list[tuple[str | None, str]] = []

    def handle(ctx, payload):
        handler_calls.append(ctx.job_id)
        return {}

    def on_success(db, job, result):
        dream = db.get(Dream, job.dream_id)
        assert dream is not None
        dream.confirmed_text = "should-rollback"
        db.flush()
        raise error

    def on_failure(db, job, error_code, error_message):
        failure_calls.append((error_code, error_message))

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)
    monkeypatch.setitem(ON_SUCCESS, JobType.GENERATE_SCENES, on_success)
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_SCENES, on_failure)

    runner.run_job(job_id, {})

    assert handler_calls == [job_id]
    assert failure_calls == [(code, message)]
    read_db.expire_all()
    [job] = rows.jobs(read_db)
    dream = read_db.get(Dream, dream_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == code
    assert job.error_message == message
    assert dream is not None and dream.confirmed_text == original


def test_retry_in_the_middle_does_not_call_on_failure(monkeypatch, session_factory, read_db):
    dream_id = _dream()
    job_id = _job(session_factory, dream_id)
    handler_calls: list[int] = []
    success_calls: list[dict] = []
    failure_calls: list[int] = []

    def handle(ctx, payload):
        handler_calls.append(ctx.job_id)
        if len(handler_calls) <= 2:
            raise JobError(FailureCode.TIMEOUT, "시간 초과", retryable=True)
        return {"done": True}

    def on_success(db, job, result):
        success_calls.append(result)

    def on_failure(db, job, error_code, error_message):
        failure_calls.append(job.attempt)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)
    monkeypatch.setitem(ON_SUCCESS, JobType.GENERATE_SCENES, on_success)
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_SCENES, on_failure)

    runner.run_job(job_id, {})

    assert len(handler_calls) == 3
    assert success_calls == [{"done": True}]
    assert failure_calls == []
    read_db.expire_all()
    [job] = rows.jobs(read_db)
    assert job.status == JobStatus.SUCCEEDED
    assert job.attempt == 3


def test_on_failure_runs_once_when_retries_are_exhausted(monkeypatch, session_factory, read_db):
    dream_id = _dream()
    job_id = _job(session_factory, dream_id)
    handler_calls: list[int] = []
    failure_calls: list[tuple[int, str | None, str]] = []

    def handle(ctx, payload):
        handler_calls.append(1)
        raise JobError(FailureCode.PROVIDER_ERROR, "일시 오류", retryable=True)

    def on_failure(db, job, error_code, error_message):
        dream = db.get(Dream, job.dream_id)
        assert dream is not None
        dream.confirmed_text = "failed-hook"
        db.flush()
        failure_calls.append((job.attempt, error_code, error_message))

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_SCENES, on_failure)

    runner.run_job(job_id, {})

    assert len(handler_calls) == 3
    assert failure_calls == [(3, "PROVIDER_ERROR", "일시 오류")]
    read_db.expire_all()
    [job] = rows.jobs(read_db)
    dream = read_db.get(Dream, dream_id)
    assert job.status == JobStatus.FAILED
    assert job.attempt == 3
    assert dream is not None and dream.confirmed_text == "failed-hook"


def test_startup_calls_on_failure_for_interrupted_jobs(monkeypatch, session_factory, read_db):
    dream_id = _dream()
    running_id = _job(session_factory, dream_id, status=JobStatus.RUNNING)
    queued_id = _job(session_factory, dream_id, JobType.GENERATE_IMAGE, target_id=1)
    done_id = _job(session_factory, dream_id, JobType.GENERATE_IMAGE, target_id=2, status=JobStatus.SUCCEEDED)
    calls: list[tuple[int, str, str | None, str]] = []

    def on_failure(db, job, error_code, error_message):
        calls.append((job.id, job.type, error_code, error_message))

    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_SCENES, on_failure)
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_IMAGE, on_failure)

    assert runner.recover_interrupted() == 2

    assert calls == [
        (running_id, JobType.GENERATE_SCENES, "INTERRUPTED", RUNNING_INTERRUPTED_MESSAGE),
        (queued_id, JobType.GENERATE_IMAGE, "INTERRUPTED", QUEUED_INTERRUPTED_MESSAGE),
    ]
    assert done_id not in {job_id for job_id, *_ in calls}
    read_db.expire_all()
    by_id = {job.id: job for job in rows.jobs(read_db)}
    assert by_id[running_id].status == JobStatus.FAILED
    assert by_id[queued_id].error_code == "INTERRUPTED"
    assert by_id[done_id].status == JobStatus.SUCCEEDED


def test_startup_on_failure_error_does_not_stop_the_next_job(monkeypatch, session_factory, caplog):
    dream_id = _dream()
    running_id = _job(session_factory, dream_id, status=JobStatus.RUNNING)
    queued_id = _job(session_factory, dream_id, JobType.GENERATE_IMAGE, target_id=1)
    seen: list[int] = []

    def on_failure(db, job, error_code, error_message):
        seen.append(job.id)
        if job.id == running_id:
            raise RuntimeError("후처리 실패")

    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_SCENES, on_failure)
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_IMAGE, on_failure)

    with caplog.at_level(logging.ERROR):
        assert runner.recover_interrupted() == 2

    assert seen == [running_id, queued_id]
    assert "후처리 실패" in caplog.text
    assert "Traceback" in caplog.text


def test_on_failure_error_does_not_stop_the_runner(monkeypatch, session_factory, read_db, caplog):
    dream_id = _dream()
    job_id = _job(session_factory, dream_id)

    def handle(ctx, payload):
        raise JobError(FailureCode.LLM_SCHEMA, "실패")

    def on_failure(db, job, error_code, error_message):
        raise RuntimeError("hook boom")

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_SCENES, on_failure)

    with caplog.at_level(logging.ERROR):
        runner.run_job(job_id, {})

    assert "hook boom" in caplog.text
    assert "Traceback" in caplog.text
    read_db.expire_all()
    [job] = rows.jobs(read_db)
    assert job.status == JobStatus.FAILED
    assert job.error_code == FailureCode.LLM_SCHEMA


def test_submit_job_returns_the_active_job(monkeypatch, session_factory, read_db):
    dream_id = _dream()
    scheduled: list[tuple[int, dict]] = []

    def fake_schedule(background_tasks, job_id, payload=None):
        scheduled.append((job_id, payload))

    monkeypatch.setattr(runner, "schedule", fake_schedule)
    background_tasks = BackgroundTasks()
    with session_factory() as db:
        first, created = submit_job(
            db,
            background_tasks,
            dream_id=dream_id,
            job_type=JobType.GENERATE_IMAGE,
            target_id=7,
            payload={"scene": 1},
        )
        second, again = submit_job(
            db,
            background_tasks,
            dream_id=dream_id,
            job_type=JobType.GENERATE_IMAGE,
            target_id=7,
            payload={"scene": 2},
        )

    assert created is True
    assert again is False
    assert first.id == second.id
    assert scheduled == [(first.id, {"scene": 1})]
    read_db.expire_all()
    [job] = rows.jobs(read_db)
    assert job.id == first.id
    assert job.status == JobStatus.QUEUED


def test_concurrent_submit_runs_handler_once(monkeypatch, session_factory, read_db):
    """다섯 요청이 겹쳐도 핸들러는 한 번이다. 첫 실행은 나머지가 끝날 때까지 running으로 둔다."""
    dream_id = _dream()
    calls: list[int] = []
    lock = threading.Lock()
    release = threading.Event()
    state = {"inside": 0, "outside": 0}

    def handle(ctx, payload):
        with lock:
            calls.append(ctx.job_id)
            state["inside"] += 1
            if state["inside"] + state["outside"] >= 5:
                release.set()
        assert release.wait(5)
        return {}

    def run_now(background_tasks, job_id, payload=None):
        runner.run_job(job_id, payload or {})

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)
    monkeypatch.setitem(ON_SUCCESS, JobType.GENERATE_SCENES, lambda db, job, result: None)
    monkeypatch.setattr(runner, "schedule", run_now)
    barrier = threading.Barrier(5)

    def once():
        barrier.wait(5)
        try:
            with session_factory() as db:
                submit_job(
                    db,
                    BackgroundTasks(),
                    dream_id=dream_id,
                    job_type=JobType.GENERATE_SCENES,
                    target_id=None,
                )
        finally:
            with lock:
                state["outside"] += 1
                if state["inside"] >= 1 and state["inside"] + state["outside"] >= 5:
                    release.set()

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(once) for _ in range(5)]
        for future in futures:
            future.result(timeout=30)
    assert len(calls) == 1
    assert len(set(calls)) == 1
    read_db.expire_all()
    [job] = rows.jobs(read_db)
    assert calls == [job.id]
    assert job.status == JobStatus.SUCCEEDED


def test_second_run_job_does_nothing(monkeypatch, session_factory, read_db):
    dream_id = _dream()
    job_id = _job(session_factory, dream_id)
    handler_calls: list[int] = []
    success_calls: list[int] = []
    failure_calls: list[int] = []
    events: list[object] = []

    def handle(ctx, payload):
        handler_calls.append(ctx.job_id)
        return {}

    def on_success(db, job, result):
        success_calls.append(job.id)

    def on_failure(db, job, error_code, error_message):
        failure_calls.append(job.id)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)
    monkeypatch.setitem(ON_SUCCESS, JobType.GENERATE_SCENES, on_success)
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_SCENES, on_failure)
    monkeypatch.setattr(runner, "publish_job_event", events.append)

    runner.run_job(job_id, {})
    assert handler_calls == [job_id]
    handler_calls.clear()
    success_calls.clear()
    failure_calls.clear()
    events.clear()

    runner.run_job(job_id, {})

    assert handler_calls == []
    assert success_calls == []
    assert failure_calls == []
    assert events == []
    read_db.expire_all()
    [job] = rows.jobs(read_db)
    assert job.id == job_id
    assert job.status == JobStatus.SUCCEEDED
    assert job.attempt == 1
    assert job.started_at is not None
