"""generate_narration 작업 연결과 images_ready 조건.

나레이션 핸들러는 가짜다. 실제 TTS는 부르지 않고, 저장·상태 변경은 실제 DB에 한다.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.config import settings
from app.core.enums import FailureCode, JobStatus, JobType
from app.jobs import runner
from app.jobs.context import JobError
from app.jobs.handlers import scenes as scene_jobs
from app.jobs.handlers.images import fake_generate_image
from app.jobs.registry import HANDLERS
from app.llm import client as llm_client
from app.llm.schemas import Scene as LlmScene
from app.llm.schemas import SceneSplitResult
from app.main import app
from app.models import Scene
from app.repositories import dreams as dream_repo
from app.repositories import jobs as job_repo
from app.repositories import scenes as scene_repo
from tests.api import rows
from tests.llm_fakes import FakeLlm

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}
LONG_TEXT = "가" * 250
BLANK_TEXT = "  \n  "


def _fake_narration(ctx, payload):
    return {}


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client, "openai_complete", fake)
    return fake


@pytest.fixture(autouse=True)
def narration_off(monkeypatch):
    """기본은 꺼 둔다. 켜는 테스트만 narration_enabled를 True로 바꾼다."""
    monkeypatch.setattr(settings, "narration_enabled", False)
    monkeypatch.setitem(HANDLERS, JobType.GENERATE_NARRATION, _fake_narration)


@pytest.fixture
def pending(monkeypatch) -> list[tuple[int, dict]]:
    """장면 생성 뒤 다음 작업을 바로 실행하지 않고 (job_id, payload)로 모은다."""
    queued: list[tuple[int, dict]] = []
    monkeypatch.setattr(runner, "enqueue", lambda job_id, payload=None: queued.append((job_id, payload or {})))
    return queued


def _status(dream_id: int) -> str:
    return client.get(f"/dreams/{dream_id}").json()["status"]


def _versions(read_db: Session) -> list:
    read_db.expire_all()
    scenes = read_db.scalars(select(Scene).options(selectinload(Scene.current_version)).order_by(Scene.order))
    return [scene.current_version for scene in scenes]


def _jobs_by_id(read_db: Session) -> dict:
    read_db.expire_all()
    return {row.id: row for row in rows.jobs(read_db)}


def _followups(read_db: Session, pending: list[tuple[int, dict]]):
    saved = _jobs_by_id(read_db)
    images, narrations = [], []
    for job_id, payload in pending:
        row = saved[job_id]
        if row.type == JobType.GENERATE_IMAGE:
            images.append((row, payload))
        elif row.type == JobType.GENERATE_NARRATION:
            narrations.append((row, payload))
    return images, narrations


def _prepare_dream() -> int:
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]
    for question in questions:
        client.post(f"/dreams/{dream_id}/interview", json={"question_id": question["question_id"], "skipped": True})
    elements = client.get(f"/dreams/{dream_id}/elements").json()["elements"]
    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": element["element_id"], "confidence": "high"} for element in elements]},
    )
    assert res.status_code == 200, res.text
    return dream_id


def _scenes_ready(monkeypatch, scene_count: int = 3, scenes: list[dict] | None = None) -> int:
    """인터뷰·확신도·장면 생성까지 끝낸 꿈. 다음 작업은 queued로 남는다(pending 픽스처 필요)."""
    dream_id = _prepare_dream()
    if scenes is None:

        def split(text, answers, extracted, complete=None):
            names = [element.name for element in extracted]
            return SceneSplitResult(
                scenes=[
                    LlmScene(
                        order=order,
                        summary_ko=f"장면 {order}",
                        element_names=names,
                        image_prompt_en=f"prompt {order}",
                    )
                    for order in range(1, scene_count + 1)
                ],
                characters=[],
            )

        monkeypatch.setattr(scene_jobs, "split_scenes", split)
    else:

        def handle(ctx, payload):
            return {"scenes": scenes, "characters": [], "elements": payload["elements"]}

        monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)

    job_id = client.post(f"/dreams/{dream_id}/jobs", json={"type": "generate_scenes"}).json()["job_id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "succeeded"
    assert _status(dream_id) == "scenes_ready"
    return dream_id


def _enable(monkeypatch):
    monkeypatch.setattr(settings, "narration_enabled", True)


def test_disabled_creates_no_narration_and_images_finish_the_flow(monkeypatch, pending, read_db):
    dream_id = _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)

    assert narrations == []
    assert len(images) == 3
    assert [row.type for row in rows.jobs(read_db) if row.type == JobType.GENERATE_NARRATION] == []

    for row, payload in images:
        runner.run_job(row.id, payload)

    assert _status(dream_id) == "images_ready"


def test_enabled_creates_one_narration_per_scene(monkeypatch, pending, read_db):
    _enable(monkeypatch)
    _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)
    versions = {version.scene_id: version for version in _versions(read_db)}

    assert len(images) == 3
    assert len(narrations) == 3
    for row, payload in narrations:
        version = versions[payload["scene_id"]]
        assert row.target_id == version.id
        assert payload == {
            "scene_id": version.scene_id,
            "version_no": version.version_no,
            "text": version.summary_ko,
        }


def test_long_text_is_cut_and_blank_text_is_skipped(monkeypatch, pending, read_db, caplog):
    _enable(monkeypatch)
    scenes = [
        {"order": 1, "summary_ko": BLANK_TEXT, "element_names": [], "image_prompt_en": "blank"},
        {"order": 2, "summary_ko": LONG_TEXT, "element_names": [], "image_prompt_en": "long"},
        {"order": 3, "summary_ko": "짧은 문장", "element_names": [], "image_prompt_en": "short"},
    ]
    with caplog.at_level(logging.INFO):
        _scenes_ready(monkeypatch, scenes=scenes)

    images, narrations = _followups(read_db, pending)
    versions = {version.scene_id: version for version in _versions(read_db)}
    by_prompt = {versions[payload["scene_id"]].prompt_en: (row, payload) for row, payload in narrations}

    assert len(images) == 3
    assert set(by_prompt) == {"long", "short"}
    assert by_prompt["long"][1]["text"] == "가" * 200
    assert by_prompt["long"][0].target_id == versions[by_prompt["long"][1]["scene_id"]].id
    assert by_prompt["short"][1]["text"] == "짧은 문장"
    assert LONG_TEXT not in caplog.text
    assert "짧은 문장" not in caplog.text
    assert BLANK_TEXT not in caplog.text


def test_images_ready_when_narration_finishes_after_images(monkeypatch, pending, read_db):
    _enable(monkeypatch)
    dream_id = _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)

    for row, payload in images:
        runner.run_job(row.id, payload)
    assert _status(dream_id) == "scenes_ready"

    for index, (row, payload) in enumerate(narrations):
        runner.run_job(row.id, payload)
        expected = "images_ready" if index == len(narrations) - 1 else "scenes_ready"
        assert _status(dream_id) == expected


def test_images_ready_when_image_finishes_after_narration(monkeypatch, pending, read_db):
    _enable(monkeypatch)
    dream_id = _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)

    for row, payload in narrations:
        runner.run_job(row.id, payload)
    assert _status(dream_id) == "scenes_ready"

    for index, (row, payload) in enumerate(images):
        runner.run_job(row.id, payload)
        expected = "images_ready" if index == len(images) - 1 else "scenes_ready"
        assert _status(dream_id) == expected


def test_narration_failure_still_reaches_images_ready(monkeypatch, pending, read_db):
    _enable(monkeypatch)
    dream_id = _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)

    def fail(ctx, payload):
        raise JobError(FailureCode.PROVIDER_ERROR, "나레이션을 만들지 못했습니다.")

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_NARRATION, fail)
    for row, payload in images:
        runner.run_job(row.id, payload)
    assert _status(dream_id) == "scenes_ready"

    for row, payload in narrations:
        runner.run_job(row.id, payload)

    saved = _jobs_by_id(read_db)
    assert _status(dream_id) == "images_ready"
    assert [(saved[row.id].status, saved[row.id].error_code) for row, _ in narrations] == [("failed", "PROVIDER_ERROR")] * 3
    assert [version.status for version in _versions(read_db)] == [JobStatus.SUCCEEDED] * 3


def test_in_progress_narration_blocks_images_ready_and_render(monkeypatch, pending, read_db):
    _enable(monkeypatch)
    dream_id = _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)

    for row, payload in images:
        runner.run_job(row.id, payload)

    assert _status(dream_id) == "scenes_ready"
    assert all(_jobs_by_id(read_db)[row.id].status == "queued" for row, _ in narrations)
    res = client.post(f"/dreams/{dream_id}/renders")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert res.json()["error"]["detail"] == {"status": "scenes_ready"}


def test_simultaneous_finish_transitions_once(monkeypatch, pending, read_db):
    _enable(monkeypatch)
    dream_id = _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)
    for row, payload in images[:-1]:
        runner.run_job(row.id, payload)
    for row, payload in narrations[:-1]:
        runner.run_job(row.id, payload)
    assert _status(dream_id) == "scenes_ready"

    barrier = threading.Barrier(2)
    transitions: list[bool] = []
    original_transition = dream_repo.transition_status
    original_done = scene_repo.all_images_done

    def handle_image(ctx, payload):
        result = fake_generate_image(ctx, payload)
        barrier.wait(5)
        return result

    def handle_narration(ctx, payload):
        barrier.wait(5)
        return {}

    def slow_done(db, dream_id_):
        time.sleep(0.3)
        return original_done(db, dream_id_)

    def record_transition(db, dream_id_, from_, to):
        changed = original_transition(db, dream_id_, from_, to)
        transitions.append(changed)
        return changed

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, handle_image)
    monkeypatch.setitem(HANDLERS, JobType.GENERATE_NARRATION, handle_narration)
    monkeypatch.setattr(scene_repo, "all_images_done", slow_done)
    monkeypatch.setattr(dream_repo, "transition_status", record_transition)

    last = [(images[-1][0].id, images[-1][1]), (narrations[-1][0].id, narrations[-1][1])]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(runner.run_job, job_id, payload) for job_id, payload in last]
        for future in futures:
            future.result(timeout=30)

    assert transitions.count(True) == 1
    assert _status(dream_id) == "images_ready"


def test_interrupted_narration_fails_and_reaches_images_ready(
    monkeypatch, pending, read_db, session_factory: sessionmaker[Session]
):
    _enable(monkeypatch)
    dream_id = _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)
    for row, payload in images:
        runner.run_job(row.id, payload)
    assert _status(dream_id) == "scenes_ready"

    running_id = narrations[0][0].id
    with session_factory.begin() as db:
        assert job_repo.claim_job(db, running_id)

    transitions: list[bool] = []
    original_transition = dream_repo.transition_status

    def record_transition(db, dream_id_, from_, to):
        changed = original_transition(db, dream_id_, from_, to)
        transitions.append(changed)
        return changed

    monkeypatch.setattr(dream_repo, "transition_status", record_transition)
    assert runner.recover_interrupted() == len(narrations)

    saved = _jobs_by_id(read_db)
    assert [(saved[row.id].status, saved[row.id].error_code) for row, _ in narrations] == [("failed", "INTERRUPTED")] * 3
    assert saved[running_id].status == "failed"
    assert transitions.count(True) == 1
    assert _status(dream_id) == "images_ready"


def test_runner_retries_narration_once(monkeypatch, pending, read_db):
    _enable(monkeypatch)
    _scenes_ready(monkeypatch)
    _, narrations = _followups(read_db, pending)
    calls: list[int] = []

    def handle(ctx, payload):
        calls.append(ctx.job_id)
        if len(calls) == 1:
            raise JobError(FailureCode.TIMEOUT, "시간 초과", retryable=True)
        return {}

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_NARRATION, handle)
    job_id = narrations[0][0].id
    runner.run_job(job_id, narrations[0][1])

    job = _jobs_by_id(read_db)[job_id]
    assert calls == [job_id, job_id]
    assert (job.status, job.attempt) == ("succeeded", 2)


def test_retry_images_does_not_create_narration(monkeypatch, pending, read_db):
    _enable(monkeypatch)
    dream_id = _scenes_ready(monkeypatch)
    images, narrations = _followups(read_db, pending)
    failed_scene = images[1][1]["scene_id"]

    def fail_one(ctx, payload):
        if payload["scene_id"] == failed_scene:
            raise JobError(FailureCode.CONTENT_POLICY, "정책 거부")
        return fake_generate_image(ctx, payload)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, fail_one)
    for row, payload in images:
        runner.run_job(row.id, payload)

    before = [row.id for row, _ in narrations]
    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, fake_generate_image)
    res = client.post(f"/dreams/{dream_id}/images/retry")

    assert res.status_code == 202, res.text
    assert [job["type"] for job in res.json()] == ["generate_image"]
    saved = _jobs_by_id(read_db)
    assert [row.id for row in saved.values() if row.type == JobType.GENERATE_NARRATION] == before
    assert all(saved[job_id].status == "queued" for job_id in before)
    assert _status(dream_id) == "scenes_ready"
