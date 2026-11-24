"""generate_image 연결 (C-S3-02). 이미지는 가짜 핸들러로 만들고 저장·상태 변경은 실제 DB에 한다.

실제 이미지 API는 부르지 않는다. conftest가 키를 비우고 가짜 핸들러를 끼우며,
E2 핸들러를 쓰는 테스트는 get_client를 가짜 클라이언트로 바꾼다.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.config import settings
from app.core.enums import DreamStatus, ElementType, FailureCode, JobStatus, JobType
from app.jobs import runner
from app.jobs.context import JobError
from app.jobs.handlers import images as image_jobs
from app.jobs.handlers import scenes as scene_jobs
from app.jobs.handlers.images import fake_generate_image
from app.jobs.registry import HANDLERS, ON_FAILURE
from app.llm import client as llm_client
from app.llm.schemas import Scene as LlmScene
from app.llm.schemas import SceneCharacter, SceneSplitResult
from app.main import app
from app.models import Dream, Scene, SceneVersion
from app.repositories import dreams as dream_repo
from app.repositories import jobs as job_repo
from app.repositories import scenes as scene_repo
from tests.api import rows
from tests.llm_fakes import FakeLlm
from worker.image_gen import generate as image_gen
from worker.image_gen.config import image_settings as img_cfg
from worker.image_gen.generate import handle_generate_image
from worker.postprocess.confidence import confidence_style_for

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client, "openai_complete", fake)
    return fake


@pytest.fixture
def pending(monkeypatch) -> list[tuple[int, dict]]:
    """장면 생성 뒤 이미지 작업을 바로 실행하지 않고 (job_id, payload)로 모은다. 테스트가 직접 실행한다."""
    queued: list[tuple[int, dict]] = []
    monkeypatch.setattr(runner, "enqueue", lambda job_id, payload=None: queued.append((job_id, payload or {})))
    return queued


def _confidence_for(element: dict) -> str:
    # 감정은 장면 확신도에서 빠지므로 low로 두어도 시각 요소(high) 결과가 그대로여야 한다
    return "low" if element["type"] == ElementType.EMOTION else "high"


def _scenes_ready(monkeypatch, scene_count: int = 3, characters: list[SceneCharacter] | None = None) -> int:
    """인터뷰·확신도·장면 생성까지 끝낸 꿈. 이미지 작업은 queued로 남는다(pending 픽스처 필요)."""
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]
    for question in questions:
        client.post(f"/dreams/{dream_id}/interview", json={"question_id": question["question_id"], "skipped": True})
    elements = client.get(f"/dreams/{dream_id}/elements").json()["elements"]
    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": e["element_id"], "confidence": _confidence_for(e)} for e in elements]},
    )
    assert res.status_code == 200, res.text

    def split(text, answers, extracted, complete=None):
        names = [element.name for element in extracted]
        return SceneSplitResult(
            scenes=[
                LlmScene(order=order, summary_ko=f"장면 {order}", element_names=names, image_prompt_en=f"prompt {order}")
                for order in range(1, scene_count + 1)
            ],
            characters=characters or [],
        )

    monkeypatch.setattr(scene_jobs, "split_scenes", split)
    job_id = client.post(f"/dreams/{dream_id}/jobs", json={"type": "generate_scenes"}).json()["job_id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "succeeded"
    assert _status(dream_id) == "scenes_ready"
    return dream_id


def _status(dream_id: int) -> str:
    return client.get(f"/dreams/{dream_id}").json()["status"]


def _versions(read_db: Session) -> list[SceneVersion]:
    read_db.expire_all()
    scenes = read_db.scalars(select(Scene).options(selectinload(Scene.current_version)).order_by(Scene.order))
    return [scene.current_version for scene in scenes]


def _image_jobs(read_db: Session) -> list:
    read_db.expire_all()
    return [row for row in rows.jobs(read_db) if row.type == JobType.GENERATE_IMAGE.value]


def _fail_scene(scene_id: int, error: JobError):
    def handle(ctx, payload):
        if payload["scene_id"] == scene_id:
            raise error
        return fake_generate_image(ctx, payload)

    return handle


def test_all_images_succeed_saves_results_and_images_ready(monkeypatch, pending, read_db):
    dream_id = _scenes_ready(monkeypatch)
    assert len(pending) == 3
    assert all(payload["confidence_level"] == "high" for _, payload in pending)
    assert all(payload["confidence_style"] == confidence_style_for("high") for _, payload in pending)
    assert all(
        set(payload) == {"scene_id", "version_no", "image_prompt_en", "characters", "confidence_level", "confidence_style"}
        for _, payload in pending
    )

    for job_id, payload in pending:
        runner.run_job(job_id, payload)

    assert all(row.status == "succeeded" and row.attempt == 1 for row in _image_jobs(read_db))
    for version in _versions(read_db):
        assert version.status == JobStatus.SUCCEEDED
        assert version.image_path == f"dreams/{dream_id}/scenes/{version.scene_id}/v1/original.png"
        assert version.final_prompt and "prompt" in version.final_prompt
        assert version.model == image_jobs.FAKE_MODEL
        assert version.settings == {"size": img_cfg.image_size, "quality": img_cfg.image_quality}
        assert version.seed is None
        assert version.generated_at is not None
        assert version.confidence_level == "high"
        with Image.open(settings.storage_path / version.image_path) as png:
            assert png.format == "PNG"
            assert f"{png.width}x{png.height}" == img_cfg.image_size
    assert _status(dream_id) == "images_ready"


def test_failed_scene_keeps_scenes_ready_and_retry_api_regenerates_it(monkeypatch, pending, read_db):
    dream_id = _scenes_ready(monkeypatch)
    versions = _versions(read_db)
    failed_scene = versions[1].scene_id
    monkeypatch.setitem(
        HANDLERS, JobType.GENERATE_IMAGE, _fail_scene(failed_scene, JobError(FailureCode.CONTENT_POLICY, "정책 거부"))
    )

    for job_id, payload in pending:
        runner.run_job(job_id, payload)

    by_scene = {version.scene_id: version for version in _versions(read_db)}
    assert by_scene[failed_scene].status == JobStatus.FAILED
    assert by_scene[failed_scene].image_path is None
    assert by_scene[failed_scene].confidence_level is None
    assert [v.status for s, v in by_scene.items() if s != failed_scene] == ["succeeded", "succeeded"]
    failed_job = next(row for row in _image_jobs(read_db) if row.target_id == by_scene[failed_scene].id)
    assert (failed_job.status, failed_job.error_code, failed_job.attempt) == ("failed", "CONTENT_POLICY", 1)
    assert _status(dream_id) == "scenes_ready"

    # 후처리 전에 끊겨 파일만 남은 경우도 다시 만들 수 있어야 한다
    leftover = settings.storage_path / f"dreams/{dream_id}/scenes/{failed_scene}/v1/original.png"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_bytes(b"leftover")
    retried: list[dict] = []

    def record(ctx, payload):
        retried.append(dict(payload))
        return fake_generate_image(ctx, payload)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, record)
    res = client.post(f"/dreams/{dream_id}/images/retry")

    assert res.status_code == 202, res.text
    [job] = res.json()
    assert job["type"] == "generate_image"
    assert job["target_id"] == by_scene[failed_scene].id
    assert job["job_id"] != failed_job.id
    assert retried == [
        {
            "scene_id": failed_scene,
            "version_no": 1,
            "image_prompt_en": "prompt 2",
            "characters": [],
            "confidence_level": "high",
            "confidence_style": confidence_style_for("high"),
        }
    ]
    assert client.get(f"/jobs/{job['job_id']}").json()["status"] == "succeeded"
    version = next(v for v in _versions(read_db) if v.scene_id == failed_scene)
    assert version.status == JobStatus.SUCCEEDED
    assert version.confidence_level == "high"
    assert _status(dream_id) == "images_ready"


def test_retry_payload_keeps_saved_characters(monkeypatch, pending, read_db):
    expected = [{"name": "Grandmother", "appearance": "white hair"}]
    dream_id = _scenes_ready(
        monkeypatch,
        characters=[SceneCharacter(name="할머니", name_en="Grandmother", appearance_en="white hair")],
    )
    assert pending
    assert all(payload["characters"] == expected for _, payload in pending)

    versions = _versions(read_db)
    failed_scene = versions[1].scene_id
    monkeypatch.setitem(
        HANDLERS, JobType.GENERATE_IMAGE, _fail_scene(failed_scene, JobError(FailureCode.CONTENT_POLICY, "정책 거부"))
    )
    for job_id, payload in pending:
        runner.run_job(job_id, payload)

    retried: list[dict] = []

    def record(ctx, payload):
        retried.append(dict(payload))
        return fake_generate_image(ctx, payload)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, record)
    res = client.post(f"/dreams/{dream_id}/images/retry")

    assert res.status_code == 202, res.text
    assert retried == [
        {
            "scene_id": failed_scene,
            "version_no": 1,
            "image_prompt_en": "prompt 2",
            "characters": expected,
            "confidence_level": "high",
            "confidence_style": confidence_style_for("high"),
        }
    ]


def test_payload_carries_confidence_style_and_retry_keeps_it(monkeypatch, pending, read_db):
    """시각 요소 확신도는 장면 payload에 실리고, 감정만 있는 장면은 비운 뒤에도 이미지가 만들어진다."""
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]
    for question in questions:
        client.post(f"/dreams/{dream_id}/interview", json={"question_id": question["question_id"], "skipped": True})
    elements = client.get(f"/dreams/{dream_id}/elements").json()["elements"]
    chosen = {"학교 복도": "high", "할머니": "medium", "우산": "low", "바다": "high", "두려움": "low", "안도감": "low"}
    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": e["element_id"], "confidence": chosen[e["name"]]} for e in elements]},
    )
    assert res.status_code == 200, res.text

    def split(text, answers, extracted, complete=None):
        named = {
            "high": ["학교 복도"],
            "medium": ["할머니"],
            "low": ["우산"],
            "emotion": ["두려움"],
        }
        return SceneSplitResult(
            scenes=[
                LlmScene(order=order, summary_ko=f"장면 {name}", element_names=names, image_prompt_en=name)
                for order, (name, names) in enumerate(named.items(), start=1)
            ],
            characters=[],
        )

    monkeypatch.setattr(scene_jobs, "split_scenes", split)
    job_id = client.post(f"/dreams/{dream_id}/jobs", json={"type": "generate_scenes"}).json()["job_id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "succeeded"

    by_prompt = {payload["image_prompt_en"]: payload for _, payload in pending}
    for level in ("high", "medium", "low"):
        assert by_prompt[level]["confidence_level"] == level
        assert by_prompt[level]["confidence_style"] == confidence_style_for(level)
    assert by_prompt["emotion"]["confidence_level"] is None
    assert by_prompt["emotion"]["confidence_style"] is None

    emotion_job = next(job_id for job_id, payload in pending if payload["image_prompt_en"] == "emotion")
    emotion_payload = by_prompt["emotion"]
    runner.run_job(emotion_job, emotion_payload)
    emotion_version = next(version for version in _versions(read_db) if version.prompt_en == "emotion")
    assert emotion_version.status == JobStatus.SUCCEEDED
    assert emotion_version.confidence_level is None
    assert _status(dream_id) == "scenes_ready"

    medium_scene = next(version.scene_id for version in _versions(read_db) if version.prompt_en == "medium")
    monkeypatch.setitem(
        HANDLERS, JobType.GENERATE_IMAGE, _fail_scene(medium_scene, JobError(FailureCode.CONTENT_POLICY, "정책 거부"))
    )
    for queued_id, payload in pending:
        if payload["image_prompt_en"] != "emotion":
            runner.run_job(queued_id, payload)

    retried: list[dict] = []

    def record(ctx, payload):
        retried.append(dict(payload))
        return fake_generate_image(ctx, payload)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, record)
    res = client.post(f"/dreams/{dream_id}/images/retry")

    assert res.status_code == 202, res.text
    assert retried == [by_prompt["medium"]]
    assert client.get(f"/jobs/{res.json()[0]['job_id']}").json()["status"] == "succeeded"


def test_last_two_scenes_finishing_together_transition_once(monkeypatch, pending, read_db):
    dream_id = _scenes_ready(monkeypatch)
    (first_id, first_payload), *last_two = pending
    runner.run_job(first_id, first_payload)
    assert _status(dream_id) == "scenes_ready"

    barrier = threading.Barrier(2)
    transitions: list[bool] = []
    original_transition = dream_repo.transition_status
    original_done = scene_repo.all_images_done

    def handle(ctx, payload):
        result = fake_generate_image(ctx, payload)
        barrier.wait(5)
        return result

    def slow_done(db, dream_id_):
        # 두 후처리가 겹치는 시간을 넓힌다. 꿈 행 잠금이 없으면 둘 다 False를 읽어 전이를 놓친다
        time.sleep(0.3)
        return original_done(db, dream_id_)

    def record_transition(db, dream_id_, from_, to):
        changed = original_transition(db, dream_id_, from_, to)
        transitions.append(changed)
        return changed

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, handle)
    monkeypatch.setattr(scene_repo, "all_images_done", slow_done)
    monkeypatch.setattr(dream_repo, "transition_status", record_transition)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(runner.run_job, job_id, payload) for job_id, payload in last_two]:
            future.result(timeout=30)

    assert transitions.count(True) == 1
    assert all(row.status == "succeeded" for row in _image_jobs(read_db))
    assert _status(dream_id) == "images_ready"


def test_transition_false_is_not_a_failure(monkeypatch, pending, read_db, session_factory: sessionmaker[Session]):
    """다른 작업이 이미 images_ready로 옮겼으면 transition_status가 False여도 작업은 성공이다."""
    dream_id = _scenes_ready(monkeypatch)
    *first_two, (last_id, last_payload) = pending
    for job_id, payload in first_two:
        runner.run_job(job_id, payload)
    with session_factory.begin() as db:
        assert dream_repo.transition_status(db, dream_id, DreamStatus.SCENES_READY, DreamStatus.IMAGES_READY)

    runner.run_job(last_id, last_payload)

    last = next(row for row in _image_jobs(read_db) if row.id == last_id)
    assert last.status == "succeeded"
    assert all(version.status == JobStatus.SUCCEEDED for version in _versions(read_db))
    assert _status(dream_id) == "images_ready"


def test_generate_image_is_not_retried_by_runner(monkeypatch, pending, read_db):
    dream_id = _scenes_ready(monkeypatch)
    calls: list[int] = []

    def handle(ctx, payload):
        calls.append(ctx.job_id)
        raise JobError(FailureCode.TIMEOUT, "시간 초과", retryable=True)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, handle)
    job_id, payload = pending[0]

    runner.run_job(job_id, payload)

    assert calls == [job_id]
    job = next(row for row in _image_jobs(read_db) if row.id == job_id)
    assert (job.status, job.attempt, job.error_code) == ("failed", 1, "TIMEOUT")
    assert _versions(read_db)[0].status == JobStatus.FAILED
    assert _status(dream_id) == "scenes_ready"


def test_other_job_types_keep_runner_retries(monkeypatch, session_factory: sessionmaker[Session], read_db):
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    with session_factory.begin() as db:
        job_id = runner.job_repo.create_job_or_get_active(db, dream_id, JobType.GENERATE_SCENES).id
    calls: list[int] = []

    def handle(ctx, payload):
        calls.append(1)
        raise JobError(FailureCode.PROVIDER_ERROR, "일시 오류", retryable=True)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_SCENES, handle)

    runner.run_job(job_id, {})

    assert len(calls) == settings.job_max_retries + 1 == 3
    [job] = rows.jobs(read_db)
    assert (job.status, job.attempt) == ("failed", 3)


def test_real_handler_calls_image_api_at_most_three_times(monkeypatch, pending, read_db):
    """E2 핸들러를 실행기로 돌리면 장면당 API 호출은 E2 내부 재시도까지 합쳐 3번이다(실행기 재시도 0회)."""
    _scenes_ready(monkeypatch)
    calls: list[str] = []

    class FakeImages:
        def generate(self, **kwargs):
            calls.append(kwargs["prompt"])
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))

    class FakeClient:
        images = FakeImages()

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, handle_generate_image)
    monkeypatch.setattr(image_gen, "get_client", lambda: FakeClient())
    monkeypatch.setattr(image_gen, "sleep", lambda seconds: None)
    job_id, payload = pending[0]

    runner.run_job(job_id, payload)

    assert len(calls) == 1 + img_cfg.image_max_retries == 3
    job = next(row for row in _image_jobs(read_db) if row.id == job_id)
    assert (job.status, job.attempt, job.error_code) == ("failed", 1, "TIMEOUT")


def test_image_jobs_respect_max_concurrency(monkeypatch, pending, read_db):
    dream_id = _scenes_ready(monkeypatch, scene_count=5)
    monkeypatch.setattr(runner, "image_slots", threading.BoundedSemaphore(2))
    lock = threading.Lock()
    release = threading.Event()
    two_inside = threading.Event()
    state = {"inside": 0, "max": 0}

    def handle(ctx, payload):
        with lock:
            state["inside"] += 1
            state["max"] = max(state["max"], state["inside"])
            if state["inside"] == 2:
                two_inside.set()
        try:
            assert release.wait(10)
            return fake_generate_image(ctx, payload)
        finally:
            with lock:
                state["inside"] -= 1

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, handle)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(runner.run_job, job_id, payload) for job_id, payload in pending]
        assert two_inside.wait(10)
        time.sleep(0.3)  # 나머지 작업이 슬롯을 기다리는 상태가 되도록
        statuses = sorted(row.status for row in _image_jobs(read_db))
        release.set()
        for future in futures:
            future.result(timeout=30)

    assert statuses == ["queued", "queued", "queued", "running", "running"]
    assert state["max"] == 2
    assert all(row.status == "succeeded" for row in _image_jobs(read_db))
    assert _status(dream_id) == "images_ready"


def test_retry_api_rejects_other_status(monkeypatch, pending):
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    res = client.post(f"/dreams/{dream_id}/images/retry")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert res.json()["error"]["detail"] == {"status": "recorded"}

    ready = _scenes_ready(monkeypatch)
    for job_id, payload in pending:
        runner.run_job(job_id, payload)
    assert _status(ready) == "images_ready"
    res = client.post(f"/dreams/{ready}/images/retry")
    assert res.status_code == 409
    assert res.json()["error"]["detail"] == {"status": "images_ready"}

    assert client.post("/dreams/999/images/retry").status_code == 404


def test_retry_api_returns_empty_list_when_nothing_to_regenerate(session_factory: sessionmaker[Session], read_db):
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    with session_factory.begin() as db:
        dream = db.get(Dream, dream_id)
        assert dream is not None
        dream.status = DreamStatus.SCENES_READY.value

    res = client.post(f"/dreams/{dream_id}/images/retry")

    assert res.status_code == 202
    assert res.json() == []
    assert rows.jobs(read_db) == []


def test_retry_api_twice_returns_the_same_job(monkeypatch, pending, read_db):
    dream_id = _scenes_ready(monkeypatch)
    failed_scene = _versions(read_db)[0].scene_id
    monkeypatch.setitem(
        HANDLERS, JobType.GENERATE_IMAGE, _fail_scene(failed_scene, JobError(FailureCode.PROVIDER_ERROR, "실패"))
    )
    for job_id, payload in pending:
        runner.run_job(job_id, payload)
    scheduled: list[int] = []
    monkeypatch.setattr(runner, "schedule", lambda background_tasks, job_id, payload=None: scheduled.append(job_id))

    first = client.post(f"/dreams/{dream_id}/images/retry")
    second = client.post(f"/dreams/{dream_id}/images/retry")

    assert first.status_code == second.status_code == 202
    assert [job["job_id"] for job in first.json()] == [job["job_id"] for job in second.json()]
    [job] = second.json()
    assert job["status"] == "queued"
    assert scheduled == [job["job_id"]]
    version = _versions(read_db)[0]
    assert version.status == JobStatus.QUEUED
    assert len([row for row in _image_jobs(read_db) if row.target_id == version.id]) == 2


@pytest.mark.parametrize("mode", ["fake", "real"])
def test_startup_installs_image_handler_by_mode(monkeypatch, caplog, mode):
    monkeypatch.setattr(settings, "image_generation_mode", mode)

    with caplog.at_level(logging.INFO), TestClient(app):
        installed = HANDLERS[JobType.GENERATE_IMAGE]

    expected = handle_generate_image if mode == "real" else fake_generate_image
    assert installed is expected
    assert f"이미지 생성 모드: {mode}" in caplog.text


def test_scene_confidence_is_empty_when_it_cannot_be_computed(monkeypatch, pending, read_db):
    """감정만 있는 장면처럼 E1 집계가 안 되면 confidence_level은 비워 두고 이미지는 저장한다."""
    dream_id = _scenes_ready(monkeypatch)

    def no_visual(elements, scene_element_names=None):
        raise image_jobs.ConfidenceInputError("시각 요소 없음")

    monkeypatch.setattr(image_jobs, "aggregate_scene_confidence", no_visual)
    for job_id, payload in pending:
        runner.run_job(job_id, payload)

    assert all(v.confidence_level is None and v.image_path for v in _versions(read_db))
    assert _status(dream_id) == "images_ready"


def test_fake_handler_does_not_overwrite(monkeypatch, pending, read_db):
    """가짜 핸들러도 E2처럼 원본이 있으면 덮어쓰지 않는다."""
    dream_id = _scenes_ready(monkeypatch)
    job_id, payload = pending[0]
    target: Path = settings.storage_path / f"dreams/{dream_id}/scenes/{payload['scene_id']}/v1/original.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"old")

    runner.run_job(job_id, payload)

    assert target.read_bytes() == b"old"
    job = next(row for row in _image_jobs(read_db) if row.id == job_id)
    assert (job.status, job.error_code) == ("failed", "INVALID_INPUT")


def _raise_on_failure(db, job, error_code, error_message):
    raise RuntimeError("후처리 실패")


def test_interrupted_image_jobs_fail_versions_and_retry_regenerates(
    monkeypatch, pending, read_db, session_factory: sessionmaker[Session], caplog
):
    """장면 생성 commit 뒤(queued)나 실행 중(running)에 꺼져도, 재시작 후 다시 만들기로 images_ready까지 간다."""
    dream_id = _scenes_ready(monkeypatch)
    running_id = pending[0][0]
    with session_factory.begin() as db:
        assert job_repo.claim_job(db, running_id)

    with caplog.at_level(logging.WARNING, logger="app.jobs.runner"):
        assert runner.recover_interrupted() == 3

    assert f"작업 중단 처리 job_id={running_id} type=generate_image dream_id={dream_id}" in caplog.text
    assert {(row.status, row.error_code) for row in _image_jobs(read_db)} == {("failed", "INTERRUPTED")}
    assert [(v.status, v.image_path) for v in _versions(read_db)] == [(JobStatus.FAILED, None)] * 3
    assert _status(dream_id) == "scenes_ready"
    scenes = client.get(f"/dreams/{dream_id}/scenes").json()["scenes"]
    assert [(scene["status"], scene["active_job"]) for scene in scenes] == [("failed", None)] * 3

    res = client.post(f"/dreams/{dream_id}/images/retry")

    assert res.status_code == 202, res.text
    assert len(res.json()) == 3
    assert all(client.get(f"/jobs/{job['job_id']}").json()["status"] == "succeeded" for job in res.json())
    assert _status(dream_id) == "images_ready"


def test_on_failure_error_falls_back_to_failed_version(monkeypatch, pending, read_db, caplog):
    """실패 후처리가 예외를 내도 장면 버전은 failed가 되고, 다시 만들기 API로 queued가 된다."""
    dream_id = _scenes_ready(monkeypatch)
    failed_scene = _versions(read_db)[1].scene_id
    monkeypatch.setitem(
        HANDLERS, JobType.GENERATE_IMAGE, _fail_scene(failed_scene, JobError(FailureCode.CONTENT_POLICY, "정책 거부"))
    )
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_IMAGE, _raise_on_failure)

    with caplog.at_level(logging.WARNING, logger="app.jobs.runner"):
        for job_id, payload in pending:
            runner.run_job(job_id, payload)

    assert "작업 실패 후처리 오류" in caplog.text
    assert "후처리 실패" in caplog.text
    assert "작업 실패 후처리 대비책 실행" in caplog.text
    version = next(v for v in _versions(read_db) if v.scene_id == failed_scene)
    assert (version.status, version.image_path) == (JobStatus.FAILED, None)
    assert _status(dream_id) == "scenes_ready"

    scheduled: list[int] = []
    monkeypatch.setattr(runner, "schedule", lambda background_tasks, job_id, payload=None: scheduled.append(job_id))
    res = client.post(f"/dreams/{dream_id}/images/retry")

    assert res.status_code == 202, res.text
    [job] = res.json()
    assert (job["target_id"], job["status"]) == (version.id, "queued")
    assert scheduled == [job["job_id"]]
    assert next(v for v in _versions(read_db) if v.scene_id == failed_scene).status == JobStatus.QUEUED


def test_interrupted_image_on_failure_error_falls_back(monkeypatch, pending, read_db):
    """재시작 때 부르는 실패 후처리가 예외를 내도 같은 대비책으로 장면 버전이 failed가 된다."""
    dream_id = _scenes_ready(monkeypatch)
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_IMAGE, _raise_on_failure)

    assert runner.recover_interrupted() == 3

    assert [v.status for v in _versions(read_db)] == [JobStatus.FAILED] * 3
    res = client.post(f"/dreams/{dream_id}/images/retry")
    assert res.status_code == 202, res.text
    assert _status(dream_id) == "images_ready"


def test_fallback_error_is_logged_and_next_job_continues(monkeypatch, pending, read_db, caplog):
    """대비책도 실패하면 ERROR 로그만 남기고 다음 작업을 이어서 처리한다."""
    _scenes_ready(monkeypatch)
    first_version = _versions(read_db)[0].id
    monkeypatch.setitem(ON_FAILURE, JobType.GENERATE_IMAGE, _raise_on_failure)
    original = runner.FAILURE_FALLBACKS[JobType.GENERATE_IMAGE]

    def fallback(db, target_id):
        if target_id == first_version:
            raise RuntimeError("대비책 실패")
        original(db, target_id)

    monkeypatch.setitem(runner.FAILURE_FALLBACKS, JobType.GENERATE_IMAGE, fallback)

    with caplog.at_level(logging.ERROR, logger="app.jobs.runner"):
        assert runner.recover_interrupted() == 3

    failures = [r for r in caplog.records if "대비책도 실패" in r.getMessage()]
    assert len(failures) == 1 and failures[0].levelno == logging.ERROR
    assert f"target_id={first_version}" in failures[0].getMessage()
    assert [v.status for v in _versions(read_db)] == [JobStatus.QUEUED, JobStatus.FAILED, JobStatus.FAILED]
