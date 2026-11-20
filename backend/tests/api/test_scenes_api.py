"""장면 목록 GET /dreams/{id}/scenes (C-S3-03). 실제 DB, 이미지는 가짜 핸들러."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.enums import ElementType, FailureCode, JobType
from app.jobs import runner
from app.jobs.context import JobError
from app.jobs.handlers import scenes as scene_jobs
from app.jobs.handlers.images import fake_generate_image
from app.jobs.registry import HANDLERS
from app.llm import client as llm_client
from app.llm.schemas import Scene as LlmScene
from app.llm.schemas import SceneSplitResult
from app.main import app
from app.models import DreamElement, Scene, SceneVersion
from tests.llm_fakes import FakeLlm

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client, "openai_complete", fake)
    return fake


@pytest.fixture
def pending(monkeypatch) -> list[tuple[int, dict]]:
    """장면 생성 뒤 이미지 작업을 바로 실행하지 않고 (job_id, payload)로 모은다."""
    queued: list[tuple[int, dict]] = []
    monkeypatch.setattr(runner, "enqueue", lambda job_id, payload=None: queued.append((job_id, payload or {})))
    return queued


def _confidence_for(element: dict) -> str:
    return "low" if element["type"] == ElementType.EMOTION else "high"


def _rated_dream() -> tuple[int, list[dict]]:
    """인터뷰와 확신도 저장까지 끝낸 꿈과 요소 목록."""
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
    return dream_id, elements


def _generate_scenes(monkeypatch, dream_id: int) -> None:
    def split(text, answers, extracted, complete=None):
        names = [element.name for element in extracted]
        return SceneSplitResult(
            scenes=[
                LlmScene(order=order, summary_ko=f"장면 {order}", element_names=names, image_prompt_en=f"prompt {order}")
                for order in (1, 2, 3)
            ],
            characters=[],
        )

    monkeypatch.setattr(scene_jobs, "split_scenes", split)
    job_id = client.post(f"/dreams/{dream_id}/jobs", json={"type": "generate_scenes"}).json()["job_id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "succeeded"


def _scenes(dream_id: int) -> list[dict]:
    res = client.get(f"/dreams/{dream_id}/scenes")
    assert res.status_code == 200, res.text
    assert "X-Mock" not in res.headers
    return res.json()["scenes"]


def _versions(read_db: Session) -> dict[int, SceneVersion]:
    read_db.expire_all()
    scenes = read_db.scalars(select(Scene).options(selectinload(Scene.current_version)))
    return {scene.id: scene.current_version for scene in scenes}


def test_unknown_dream_returns_404():
    res = client.get("/dreams/999/scenes")

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_empty_list_before_scenes():
    dream_id, _ = _rated_dream()

    assert _scenes(dream_id) == []


def test_scenes_in_order_with_elements_and_queued_image_job(monkeypatch, pending, read_db):
    dream_id, elements = _rated_dream()
    _generate_scenes(monkeypatch, dream_id)

    scenes = _scenes(dream_id)

    assert [scene["order"] for scene in scenes] == [1, 2, 3]
    queued_job_ids = {job_id for job_id, _ in pending}
    assert len(queued_job_ids) == 3
    versions = _versions(read_db)
    for scene in scenes:
        version = versions[scene["scene_id"]]
        assert scene["version_no"] == 1
        assert scene["summary_ko"] == f"장면 {scene['order']}"
        assert scene["status"] == "queued"
        assert scene["image_url"] is None
        assert scene["confidence_level"] is None
        assert scene["elements"] == [
            {
                "element_id": e["element_id"],
                "name": e["name"],
                "type": e["type"],
                "confidence": _confidence_for(e),
            }
            for e in elements
        ]
        job = scene["active_job"]
        assert job is not None
        assert (job["type"], job["status"], job["target_id"]) == ("generate_image", "queued", version.id)
        assert job["job_id"] in queued_job_ids


def test_image_success_and_failure(monkeypatch, pending, read_db):
    dream_id, _ = _rated_dream()
    _generate_scenes(monkeypatch, dream_id)
    failed_scene = sorted(_versions(read_db))[1]

    def handle(ctx, payload):
        if payload["scene_id"] == failed_scene:
            raise JobError(FailureCode.CONTENT_POLICY, "정책 거부")
        return fake_generate_image(ctx, payload)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, handle)
    for job_id, payload in pending:
        runner.run_job(job_id, payload)

    versions = _versions(read_db)
    for scene in _scenes(dream_id):
        assert scene["active_job"] is None
        if scene["scene_id"] == failed_scene:
            assert scene["status"] == "failed"
            assert scene["image_url"] is None
            assert scene["confidence_level"] is None
            continue
        version = versions[scene["scene_id"]]
        assert version.generated_at is not None
        assert scene["status"] == "succeeded"
        assert scene["image_url"] == f"/storage/{version.image_path}?v={int(version.generated_at.timestamp())}"
        assert scene["confidence_level"] == "high"


def test_element_confidence_is_current_value(
    monkeypatch, pending, session_factory: sessionmaker[Session]
):
    dream_id, elements = _rated_dream()
    _generate_scenes(monkeypatch, dream_id)
    place = next(e for e in elements if e["type"] == ElementType.PLACE)
    assert place["element_id"] in [e["element_id"] for e in _scenes(dream_id)[0]["elements"]]

    with session_factory.begin() as db:
        db.get(DreamElement, place["element_id"]).confidence = "low"

    for scene in _scenes(dream_id):
        changed = next(e for e in scene["elements"] if e["element_id"] == place["element_id"])
        assert changed["confidence"] == "low"
