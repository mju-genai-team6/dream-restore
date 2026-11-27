"""자연어 장면 수정 POST /scenes/{scene_id}/revisions.

revise_scene은 D 함수가 아직 없어 monkeypatch로만 넣는다. 이미지는 가짜 핸들러가 만든다.
"""
import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.enums import DreamStatus, FailureCode, JobStatus, JobType
from app.jobs import runner
from app.jobs.context import JobError
from app.jobs.registry import HANDLERS
from app.llm.client import LlmSchemaError, LlmTimeoutError
from app.main import app
from app.models import Dream, DreamElement, Scene, SceneVersion
from app.repositories import scenes as scene_repo
from app.services import revision_bridge
from scripts import seed
from tests.api import rows

client = TestClient(app)

UNAVAILABLE = "장면 수정 기능을 아직 사용할 수 없습니다."
NOT_A_REVISION = "장면을 어떻게 바꿀지 다시 말해 주세요."
SUMMARY = "창밖은 호수다."
PROMPT = "A gray lake outside the school window."


@pytest.fixture(autouse=True)
def revision_off(monkeypatch):
    """설정과 나레이션은 테스트가 켜기 전까지 꺼 둔다. .env 값이 끼어들지 않게 한다."""
    monkeypatch.setattr(settings, "scene_revision_enabled", False)
    monkeypatch.setattr(settings, "narration_enabled", False)


def _dream(session_factory: sessionmaker[Session], status: DreamStatus) -> int:
    data = copy.deepcopy(next(item for item in seed.SAMPLE_DREAMS if item["status"] == status))
    with session_factory.begin() as db:
        return seed._seed_one(db, 0, data).id


def _scene(read_db: Session, dream_id: int) -> Scene:
    read_db.expire_all()
    scene = read_db.scalar(select(Scene).where(Scene.dream_id == dream_id).order_by(Scene.order))
    assert scene is not None and scene.current_version_id is not None
    return scene


def _version_count(read_db: Session, scene_id: int) -> int:
    read_db.expire_all()
    return read_db.scalar(select(func.count()).select_from(SceneVersion).where(SceneVersion.scene_id == scene_id))


def _post(scene: Scene, instruction: str = "  바다가 아니라 호수였어  ", base_version_id: int | None = None):
    return client.post(
        f"/scenes/{scene.id}/revisions",
        json={
            "instruction": instruction,
            "base_version_id": scene.current_version_id if base_version_id is None else base_version_id,
        },
    )


def _accept(scene, instruction, elements, complete=None):
    return SimpleNamespace(
        changed=True,
        summary_ko=SUMMARY,
        image_prompt_en=PROMPT,
        element_names=[elements[0].name, "없는이름"],
    )


def _enable(monkeypatch, revise=_accept):
    monkeypatch.setattr(settings, "scene_revision_enabled", True)
    monkeypatch.setattr(revision_bridge, "revise_scene", revise)


def _error(res) -> dict:
    return res.json()["error"]


def test_disabled_and_missing_function_are_409(monkeypatch, session_factory, read_db):
    dream_id = _dream(session_factory, DreamStatus.IMAGES_READY)
    scene = _scene(read_db, dream_id)
    before = _version_count(read_db, scene.id)

    monkeypatch.setattr(revision_bridge, "revise_scene", _accept)
    disabled = _post(scene)
    assert disabled.status_code == 409
    assert _error(disabled)["code"] == "INVALID_STATE"
    assert _error(disabled)["message"] == UNAVAILABLE

    monkeypatch.setattr(settings, "scene_revision_enabled", True)
    monkeypatch.setattr(revision_bridge, "revise_scene", None)
    missing = _post(scene)
    assert missing.status_code == 409
    assert _error(missing)["message"] == UNAVAILABLE
    assert _version_count(read_db, scene.id) == before


def test_rejects_wrong_state_missing_scene_and_bad_instruction(monkeypatch, session_factory, read_db):
    _enable(monkeypatch)
    dream_id = _dream(session_factory, DreamStatus.SCENES_READY)
    scene = _scene(read_db, dream_id)

    wrong_state = _post(scene)
    assert wrong_state.status_code == 409
    assert _error(wrong_state)["code"] == "INVALID_STATE"
    assert _error(wrong_state)["detail"] == {"status": "scenes_ready"}

    missing = client.post("/scenes/999999/revisions", json={"instruction": "호수로 바꿔 줘", "base_version_id": 1})
    assert missing.status_code == 404
    assert _error(missing)["code"] == "NOT_FOUND"

    for instruction in ("", "   ", "가" * 201):
        res = _post(scene, instruction=instruction)
        assert res.status_code == 400, instruction
        assert _error(res)["code"] == "VALIDATION_ERROR"


def test_version_conflict_and_not_a_revision(monkeypatch, session_factory, read_db):
    dream_id = _dream(session_factory, DreamStatus.IMAGES_READY)
    scene = _scene(read_db, dream_id)
    before = _version_count(read_db, scene.id)
    _enable(monkeypatch)

    conflict = _post(scene, base_version_id=scene.current_version_id + 1)
    assert conflict.status_code == 409
    assert _error(conflict)["code"] == "VERSION_CONFLICT"
    assert _error(conflict)["detail"] == {"current_version_id": scene.current_version_id}

    def unchanged(scene_arg, instruction, elements, complete=None):
        return SimpleNamespace(changed=False, summary_ko=SUMMARY, image_prompt_en=PROMPT, element_names=[])

    monkeypatch.setattr(revision_bridge, "revise_scene", unchanged)
    rejected = _post(scene)
    assert rejected.status_code == 400
    assert _error(rejected)["code"] == "VALIDATION_ERROR"
    assert _error(rejected)["message"] == NOT_A_REVISION
    assert _error(rejected)["detail"] == {"field": "instruction", "reason": "not_a_revision"}
    assert _version_count(read_db, scene.id) == before


def test_success_switches_current_version_and_keeps_dream_status(monkeypatch, session_factory, read_db):
    dream_id = _dream(session_factory, DreamStatus.IMAGES_READY)
    scene = _scene(read_db, dream_id)
    previous_id = scene.current_version_id
    _enable(monkeypatch)

    res = _post(scene)

    assert res.status_code == 202
    body = res.json()
    assert body["job"]["type"] == "generate_image"
    assert body["job"]["target_id"] == body["scene_version_id"]
    assert body["job"]["status"] == "queued"
    read_db.expire_all()
    scene = read_db.get(Scene, scene.id)
    version = read_db.get(SceneVersion, body["scene_version_id"])
    previous = read_db.get(SceneVersion, previous_id)
    assert scene.current_version_id == version.id
    assert version.version_no == 2
    assert version.summary_ko == SUMMARY
    assert version.prompt_en == PROMPT
    assert version.status == JobStatus.SUCCEEDED
    names = [read_db.get(DreamElement, element_id).name for element_id in version.element_ids]
    assert "없는이름" not in names
    assert names
    assert previous.status == JobStatus.SUCCEEDED
    assert read_db.get(Dream, dream_id).status == DreamStatus.IMAGES_READY
    job = next(row for row in rows.jobs(read_db) if row.id == body["job"]["job_id"])
    assert (job.type, job.status, job.target_id) == (JobType.GENERATE_IMAGE, JobStatus.SUCCEEDED, version.id)


def test_rendered_revision_makes_existing_video_not_latest(monkeypatch, session_factory, read_db):
    dream_id = _dream(session_factory, DreamStatus.RENDERED)
    before = client.get(f"/dreams/{dream_id}/renders/latest")
    assert before.status_code == 200
    assert before.json()["is_latest"] is True
    scene = _scene(read_db, dream_id)
    _enable(monkeypatch)

    res = _post(scene)

    assert res.status_code == 202
    read_db.expire_all()
    assert read_db.get(Scene, scene.id).current_version_id == res.json()["scene_version_id"]
    assert read_db.get(Dream, dream_id).status == DreamStatus.RENDERED
    latest = client.get(f"/dreams/{dream_id}/renders/latest")
    assert latest.status_code == 200
    assert latest.json()["render_id"] == before.json()["render_id"]
    assert latest.json()["is_latest"] is False


def test_image_failure_keeps_current_version(monkeypatch, session_factory, read_db):
    dream_id = _dream(session_factory, DreamStatus.IMAGES_READY)
    scene = _scene(read_db, dream_id)
    previous_id = scene.current_version_id

    def fail(ctx, payload):
        raise JobError(FailureCode.PROVIDER_ERROR, "이미지를 만들지 못했습니다.")

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, fail)
    _enable(monkeypatch)

    res = _post(scene)

    assert res.status_code == 202
    read_db.expire_all()
    failed = read_db.get(SceneVersion, res.json()["scene_version_id"])
    assert failed.status == JobStatus.FAILED
    assert failed.image_path is None
    assert read_db.get(Scene, scene.id).current_version_id == previous_id
    assert read_db.get(Dream, dream_id).status == DreamStatus.IMAGES_READY


def test_revision_in_progress_is_409_and_current_version_stays(monkeypatch, session_factory, read_db):
    dream_id = _dream(session_factory, DreamStatus.IMAGES_READY)
    scene = _scene(read_db, dream_id)
    previous_id = scene.current_version_id
    _enable(monkeypatch)
    monkeypatch.setattr(runner, "schedule", lambda *args, **kwargs: None)

    first = _post(scene)
    assert first.status_code == 202
    again = _post(scene)

    assert again.status_code == 409
    assert _error(again)["code"] == "INVALID_STATE"
    read_db.expire_all()
    assert read_db.get(Scene, scene.id).current_version_id == previous_id
    assert read_db.get(Dream, dream_id).status == DreamStatus.IMAGES_READY
    assert scene_repo.all_images_done(read_db, dream_id) is True
    assert _version_count(read_db, scene.id) == 2


def test_llm_timeout_is_504_and_schema_error_is_502(monkeypatch, session_factory, read_db):
    dream_id = _dream(session_factory, DreamStatus.IMAGES_READY)
    scene = _scene(read_db, dream_id)
    before = _version_count(read_db, scene.id)
    _enable(monkeypatch)

    def timeout(*args, **kwargs):
        raise LlmTimeoutError("late")

    monkeypatch.setattr(revision_bridge, "revise_scene", timeout)
    late = _post(scene)
    assert late.status_code == 504
    assert _error(late)["code"] == "UPSTREAM_TIMEOUT"

    def schema(*args, **kwargs):
        raise LlmSchemaError("bad json")

    monkeypatch.setattr(revision_bridge, "revise_scene", schema)
    bad = _post(scene)
    assert bad.status_code == 502
    assert _error(bad)["code"] == "LLM_FAILED"
    assert _version_count(read_db, scene.id) == before


def test_narration_job_is_created_when_enabled(monkeypatch, session_factory, read_db):
    dream_id = _dream(session_factory, DreamStatus.IMAGES_READY)
    scene = _scene(read_db, dream_id)
    previous_id = scene.current_version_id
    scheduled: list[tuple[int, dict]] = []

    def capture(background_tasks, job_id, payload=None):
        scheduled.append((job_id, payload or {}))

    _enable(monkeypatch)
    monkeypatch.setattr(settings, "narration_enabled", True)
    monkeypatch.setattr(runner, "schedule", capture)

    res = _post(scene)

    assert res.status_code == 202
    version_id = res.json()["scene_version_id"]
    read_db.expire_all()
    narration = [
        row for row in rows.jobs(read_db) if row.type == JobType.GENERATE_NARRATION and row.target_id == version_id
    ]
    assert len(narration) == 1
    assert {payload.get("version_no") for _job_id, payload in scheduled} == {2}
    assert any(payload.get("scene_id") == scene.id and "text" in payload for _job_id, payload in scheduled)
    assert read_db.get(Scene, scene.id).current_version_id == previous_id
