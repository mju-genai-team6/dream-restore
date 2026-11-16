"""작업 실행기와 작업 API (C-S2-04). 장면 생성은 가짜 처리(registry)다."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import FailureCode, JobStatus, JobType
from app.jobs import runner
from app.jobs.context import JobError
from app.jobs.registry import HANDLERS
from app.llm import client as llm_client
from app.main import app
from app.repositories import jobs as job_repo
from app.schemas.jobs import JobSummary
from app.services import jobs as job_service
from app.services.repo_bridge import QUEUED_INTERRUPTED_MESSAGE
from tests.api import rows
from tests.llm_fakes import FakeLlm
from worker.image_gen.generate import handle_generate_image
from worker.render.handler import handle_render_video

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}
SCENES = {"type": "generate_scenes"}


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client, "openai_complete", fake)
    return fake


@pytest.fixture
def events(monkeypatch) -> list[JobSummary]:
    """작업 등록(queued)과 실행기의 상태·단계 변경 이벤트를 모은다."""
    sent: list[JobSummary] = []
    monkeypatch.setattr(job_service, "publish_job_event", sent.append)
    monkeypatch.setattr(runner, "publish_job_event", sent.append)
    return sent


@pytest.fixture
def hold_jobs(monkeypatch) -> None:
    """TestClient는 응답 전에 백그라운드 작업을 끝까지 돌리므로, 실행하지 않고 queued로 남긴다."""
    monkeypatch.setattr(runner, "run_job", lambda job_id, payload: None)


def _handler(monkeypatch, *outcomes: Exception | None) -> list[int]:
    """장면 생성 처리 함수를 바꾼다. outcomes를 차례로 raise하고, None이거나 다 쓰면 성공한다."""
    calls: list[int] = []

    def handle(ctx, payload):
        calls.append(ctx.job_id)
        outcome = outcomes[len(calls) - 1] if len(calls) <= len(outcomes) else None
        if outcome is not None:
            raise outcome
        return {}

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)
    return calls


def _interviewing_dream() -> int:
    """인터뷰를 끝낸 꿈 (요소 목록은 아직 확인하지 않음)."""
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]
    client.post(
        f"/dreams/{dream_id}/interview",
        json={"question_id": questions[0]["question_id"], "answer": "분홍색 카디건을 입었어요"},
    )
    for q in questions[1:]:
        client.post(f"/dreams/{dream_id}/interview", json={"question_id": q["question_id"], "skipped": True})
    return dream_id


def _ready_dream(rated: int | None = None) -> tuple[int, list[int]]:
    """재추출까지 끝낸 꿈. 앞에서부터 rated개 요소에 확신도를 저장한다(None이면 전부)."""
    dream_id = _interviewing_dream()
    element_ids = [e["element_id"] for e in client.get(f"/dreams/{dream_id}/elements").json()["elements"]]
    targets = element_ids if rated is None else element_ids[:rated]
    if targets:
        res = client.put(
            f"/dreams/{dream_id}/elements/confidence",
            json={"items": [{"element_id": i, "confidence": "high"} for i in targets]},
        )
        assert res.status_code == 200, res.text
    return dream_id, element_ids


def _request(dream_id: int):
    return client.post(f"/dreams/{dream_id}/jobs", json=SCENES)


def _job(job_id: int) -> dict:
    res = client.get(f"/jobs/{job_id}")
    assert res.status_code == 200, res.text
    return res.json()


def test_five_requests_return_one_job(hold_jobs, read_db):
    dream_id, _ = _ready_dream()

    responses = [_request(dream_id) for _ in range(5)]

    assert [r.status_code for r in responses] == [202] * 5
    assert len({r.json()["job_id"] for r in responses}) == 1
    assert responses[0].json()["status"] == "queued"
    assert "X-Mock" not in responses[0].headers
    [job] = rows.jobs(read_db)
    assert (job.type, job.status, job.target_id, job.attempt) == ("generate_scenes", "queued", None, 0)


def test_concurrent_requests_return_one_job(hold_jobs, read_db):
    dream_id, _ = _ready_dream()

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: _request(dream_id), range(5)))

    assert [r.status_code for r in responses] == [202] * 5
    assert len({r.json()["job_id"] for r in responses}) == 1
    assert len(rows.jobs(read_db)) == 1


def test_fake_job_goes_queued_running_succeeded(events, read_db):
    dream_id, _ = _ready_dream()

    res = _request(dream_id)

    assert res.status_code == 202, res.text
    created = res.json()
    assert created["status"] == "queued"
    assert created["dream_id"] == dream_id
    assert created["attempt"] == 0
    assert created["started_at"] is None
    assert [(e.status, e.stage) for e in events] == [
        ("queued", None),
        ("running", None),
        ("running", "splitting"),
        ("running", "prompting"),
        ("succeeded", "prompting"),
    ]
    assert {e.job_id for e in events} == {created["job_id"]}

    job = _job(created["job_id"])
    assert job["status"] == "succeeded"
    assert job["stage"] == "prompting"
    assert job["attempt"] == 1
    assert job["error"] is None
    assert job["started_at"] is not None
    assert job["finished_at"] is not None
    # 가짜 처리는 꿈 상태를 바꾸지 않는다 (C-S3-01에서 scenes_ready)
    assert client.get(f"/dreams/{dream_id}").json()["status"] == "interviewing"


def test_retryable_failure_then_success(monkeypatch):
    calls = _handler(monkeypatch, JobError(FailureCode.TIMEOUT, "시간 초과", retryable=True))
    dream_id, _ = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert len(calls) == 2
    assert job["status"] == "succeeded"
    assert job["attempt"] == 2
    assert job["error"] is None


def test_retryable_failure_stops_after_two_retries(monkeypatch):
    error = JobError(FailureCode.PROVIDER_ERROR, "일시 오류", retryable=True)
    calls = _handler(monkeypatch, error, error, error, error)
    dream_id, _ = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert len(calls) == 3
    assert job["status"] == "failed"
    assert job["attempt"] == 3
    assert job["error"] == {"code": "PROVIDER_ERROR", "message": "일시 오류"}


@pytest.mark.parametrize(
    "error",
    [
        JobError(FailureCode.LLM_SCHEMA, "장면을 만들지 못했습니다."),
        JobError(FailureCode.CONTENT_POLICY, "정책 거부", retryable=True),
    ],
)
def test_non_retryable_failure_fails_immediately(monkeypatch, read_db, error):
    calls = _handler(monkeypatch, error)
    dream_id, _ = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert len(calls) == 1
    assert job["status"] == "failed"
    assert job["attempt"] == 1
    assert job["error"] == {"code": error.code.value, "message": error.message}
    assert job["finished_at"] is not None
    [row] = rows.jobs(read_db)
    assert row.error_code == error.code.value


def test_unexpected_exception_fails_as_internal_error(monkeypatch, read_db):
    calls = _handler(monkeypatch, RuntimeError("버그"))
    dream_id, _ = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert len(calls) == 1
    assert job["status"] == "failed"
    assert job["attempt"] == 1
    assert job["error"] == {"code": "INTERNAL_ERROR", "message": runner.INTERNAL_ERROR_MESSAGE}
    [row] = rows.jobs(read_db)
    assert row.error_code is None
    assert row.error_message == runner.INTERNAL_ERROR_MESSAGE


def test_failed_job_can_be_requested_again(monkeypatch):
    _handler(monkeypatch, JobError(FailureCode.LLM_SCHEMA, "실패"))
    dream_id, _ = _ready_dream()
    first = _request(dream_id).json()["job_id"]

    second = _request(dream_id)

    assert second.status_code == 202
    assert second.json()["job_id"] != first
    assert _job(second.json()["job_id"])["status"] == "succeeded"


def test_startup_marks_running_and_queued_jobs_interrupted(session_factory: sessionmaker[Session], read_db):
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    with session_factory.begin() as db:
        running = job_repo.create_job_or_get_active(db, dream_id, JobType.GENERATE_SCENES)
        job_repo.update_job(db, running.id, status=JobStatus.RUNNING)
        queued = job_repo.create_job_or_get_active(db, dream_id, JobType.GENERATE_IMAGE, target_id=1)
        done = job_repo.create_job_or_get_active(db, dream_id, JobType.GENERATE_IMAGE, target_id=2)
        job_repo.update_job(db, done.id, status=JobStatus.SUCCEEDED)

    with TestClient(app):
        pass

    by_id = {job.id: job for job in rows.jobs(read_db)}
    for job_id in (running.id, queued.id):
        assert by_id[job_id].status == "failed"
        assert by_id[job_id].error_code == "INTERRUPTED"
        assert by_id[job_id].finished_at is not None
    assert by_id[queued.id].error_message == QUEUED_INTERRUPTED_MESSAGE
    assert by_id[done.id].status == "succeeded"
    assert _job(running.id)["error"]["code"] == "INTERRUPTED"


def test_scenes_request_rejected_before_interview():
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]

    res = _request(dream_id)

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert res.json()["error"]["detail"] == {"status": "recorded"}


def test_scenes_request_rejected_before_reextract(read_db):
    dream_id = _interviewing_dream()

    res = _request(dream_id)

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert res.json()["error"]["detail"] == {"status": "interviewing"}
    assert rows.jobs(read_db) == []


def test_scenes_request_rejected_with_empty_confidence(read_db):
    dream_id, element_ids = _ready_dream(rated=2)

    res = _request(dream_id)

    assert res.status_code == 409
    error = res.json()["error"]
    assert error["code"] == "INVALID_STATE"
    assert error["detail"] == {"element_ids": element_ids[2:]}
    assert rows.jobs(read_db) == []


def test_scenes_request_unknown_dream_returns_not_found():
    res = _request(999)

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_confidence_rejected_while_scenes_job_is_active(hold_jobs):
    dream_id, element_ids = _ready_dream()
    job_id = _request(dream_id).json()["job_id"]

    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": element_ids[0], "confidence": "low"}]},
    )

    assert res.status_code == 409
    error = res.json()["error"]
    assert error["code"] == "INVALID_STATE"
    assert error["detail"] == {"status": "interviewing", "job_id": job_id}


def test_confidence_allowed_after_scenes_job_failed(monkeypatch):
    _handler(monkeypatch, JobError(FailureCode.LLM_SCHEMA, "실패"))
    dream_id, element_ids = _ready_dream()
    assert _job(_request(dream_id).json()["job_id"])["status"] == "failed"

    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": element_ids[0], "confidence": "low"}]},
    )

    assert res.status_code == 200, res.text


def test_unknown_job_returns_not_found():
    res = client.get("/jobs/999")

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"
    assert res.json()["error"]["detail"] == {"job_id": 999}


def test_dream_active_job_shows_scenes_job_only(hold_jobs, session_factory: sessionmaker[Session]):
    dream_id, _ = _ready_dream()
    with session_factory.begin() as db:
        job_repo.create_job_or_get_active(db, dream_id, JobType.GENERATE_IMAGE, target_id=1)
    assert client.get(f"/dreams/{dream_id}").json()["active_job"] is None

    job_id = _request(dream_id).json()["job_id"]
    with session_factory.begin() as db:
        job_repo.create_job_or_get_active(db, dream_id, JobType.GENERATE_IMAGE, target_id=2)

    active = client.get(f"/dreams/{dream_id}").json()["active_job"]
    assert active["job_id"] == job_id
    assert active["type"] == "generate_scenes"
    assert active["status"] == "queued"
    assert active["dream_id"] == dream_id


def test_dream_active_job_is_null_after_job_finishes():
    dream_id, _ = _ready_dream()
    assert _job(_request(dream_id).json()["job_id"])["status"] == "succeeded"

    assert client.get(f"/dreams/{dream_id}").json()["active_job"] is None


def test_worker_handlers_stay_registered():
    assert HANDLERS[JobType.RENDER_VIDEO] is handle_render_video
    assert HANDLERS[JobType.GENERATE_IMAGE] is handle_generate_image
    assert JobType.GENERATE_SCENES in HANDLERS
