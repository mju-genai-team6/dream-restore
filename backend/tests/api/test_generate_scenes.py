"""generate_scenes 연결 (C-S3-01). split_scenes만 가짜로 바꾸고 저장은 실제 DB에 한다."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import DreamStatus, ElementType, JobType
from app.jobs import runner
from app.jobs.handlers import scenes as scene_jobs
from app.jobs.handlers.images import fake_generate_image
from app.jobs.registry import HANDLERS
from app.llm import client as llm_client
from app.llm.client import LlmCallError, LlmSchemaError, LlmTimeoutError
from app.llm.schemas import Scene as LlmScene
from app.llm.schemas import SceneCharacter, SceneSplitResult
from app.main import app
from app.models import Dream, Scene, SceneVersion
from tests.api import rows
from tests.llm_fakes import FakeLlm

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}
SCENES = {"type": "generate_scenes"}


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client, "openai_complete", fake)
    return fake


@pytest.fixture(autouse=True)
def image_calls(monkeypatch) -> list[dict]:
    """가짜 이미지 핸들러 앞에서 payload를 기록하고, commit 뒤에 실행되는지 확인한다."""
    calls: list[dict] = []

    def fake(ctx, payload):
        assert "confidence_style" not in payload
        with runner.session_factory() as db:
            dream = db.get(Dream, ctx.dream_id)
            assert dream is not None
            assert dream.status == DreamStatus.SCENES_READY.value
            scene = db.get(Scene, payload["scene_id"])
            assert scene is not None and scene.current_version_id is not None
            version = db.get(SceneVersion, scene.current_version_id)
            assert version is not None
            assert version.version_no == payload["version_no"]
        calls.append(dict(payload))
        return fake_generate_image(ctx, payload)

    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, fake)
    monkeypatch.setattr(runner, "enqueue", runner.run_job)
    return calls


def _interviewing_dream() -> int:
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]
    client.post(
        f"/dreams/{dream_id}/interview",
        json={"question_id": questions[0]["question_id"], "answer": "분홍색 카디건을 입었어요"},
    )
    for question in questions[1:]:
        client.post(f"/dreams/{dream_id}/interview", json={"question_id": question["question_id"], "skipped": True})
    return dream_id


def _ready_dream() -> tuple[int, list[dict]]:
    dream_id = _interviewing_dream()
    elements = client.get(f"/dreams/{dream_id}/elements").json()["elements"]
    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": item["element_id"], "confidence": "high"} for item in elements]},
    )
    assert res.status_code == 200, res.text
    return dream_id, elements


def _request(dream_id: int):
    return client.post(f"/dreams/{dream_id}/jobs", json=SCENES)


def _job(job_id: int) -> dict:
    res = client.get(f"/jobs/{job_id}")
    assert res.status_code == 200, res.text
    return res.json()


def _stored_scenes(read_db: Session) -> list[Scene]:
    read_db.expire_all()
    return list(
        read_db.scalars(select(Scene).options(selectinload(Scene.current_version)).order_by(Scene.order))
    )


def _split_result(elements: list, *, bad_name: str | None = None) -> SceneSplitResult:
    names = [element.name for element in elements]
    if bad_name is not None:
        names = [bad_name, *names]
    scenes = [
        LlmScene(order=order, summary_ko=f"장면 {order}", element_names=list(names), image_prompt_en=f"prompt {order}")
        for order in (1, 2, 3)
    ]
    characters = [
        SceneCharacter(name=element.name, name_en="Grandmother", appearance_en="white hair")
        for element in elements
        if element.type == ElementType.PERSON
    ]
    return SceneSplitResult(scenes=scenes, characters=characters)


def test_success_saves_scenes_and_schedules_images(monkeypatch, read_db, image_calls):
    seen: dict = {}

    def fake(text, answers, elements, complete=None):
        seen["text"] = text
        seen["answers"] = [(item.question, item.answer) for item in answers]
        seen["confidences"] = [element.model_dump()["name"] for element in elements]
        return _split_result(elements)

    monkeypatch.setattr(scene_jobs, "split_scenes", fake)
    dream_id, elements = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert job["status"] == "succeeded"
    assert job["attempt"] == 1
    assert seen["text"] == TEXT["text"]
    assert seen["answers"][0] == ("복도에서 기억나는 것을 자유롭게 말해 주세요.", "분홍색 카디건을 입었어요")
    assert all(answer is None for _, answer in seen["answers"][1:])
    assert seen["confidences"] == [item["name"] for item in elements]
    # 이미지 작업도 바로 실행되어(enqueue = run_job) 세 장면 모두 끝났다
    assert client.get(f"/dreams/{dream_id}").json()["status"] == "images_ready"

    stored = _stored_scenes(read_db)
    assert [scene.order for scene in stored] == [1, 2, 3]
    expected_ids = [item["element_id"] for item in elements]
    for scene in stored:
        version = scene.current_version
        assert version is not None
        assert scene.current_version_id == version.id
        assert version.version_no == 1
        assert version.summary_ko == f"장면 {scene.order}"
        assert version.prompt_en == f"prompt {scene.order}"
        assert [int(element_id) for element_id in version.element_ids] == expected_ids
        assert version.image_path == f"dreams/{dream_id}/scenes/{scene.id}/v1/original.png"

    image_jobs = [row for row in rows.jobs(read_db) if row.type == JobType.GENERATE_IMAGE.value]
    assert len(image_jobs) == 3
    assert {row.target_id for row in image_jobs} == {scene.current_version_id for scene in stored}
    assert all(row.status == "succeeded" for row in image_jobs)
    assert len(image_calls) == 3
    assert {call["scene_id"] for call in image_calls} == {scene.id for scene in stored}
    assert {call["version_no"] for call in image_calls} == {1}
    assert all(call["characters"] == [{"name": "Grandmother", "appearance": "white hair"}] for call in image_calls)
    assert all("confidence_style" not in call for call in image_calls)
    people = [
        element
        for element in rows.elements_of(read_db, rows.extractions(read_db)[-1].id)
        if element.type == ElementType.PERSON.value
    ]
    assert [(element.name, element.name_en, element.appearance_en) for element in people] == [
        ("할머니", "Grandmother", "white hair")
    ]


def test_unknown_character_name_saves_scenes_without_appearance(monkeypatch, read_db, image_calls):
    def fake(text, answers, elements, complete=None):
        result = _split_result(elements)
        result.characters.append(SceneCharacter(name="없는사람", name_en="nobody", appearance_en="tall"))
        return result

    monkeypatch.setattr(scene_jobs, "split_scenes", fake)
    dream_id, _elements = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert job["status"] == "succeeded"
    assert len(_stored_scenes(read_db)) == 3
    stored = rows.elements_of(read_db, rows.extractions(read_db)[-1].id)
    assert stored
    assert all(element.name_en is None and element.appearance_en == "" for element in stored)
    assert image_calls
    assert all(call["characters"] == [] for call in image_calls)


def test_unknown_element_name_fails_and_can_retry(monkeypatch, read_db):
    calls: list[int] = []
    bad = {"on": True}

    def fake(text, answers, elements, complete=None):
        calls.append(1)
        return _split_result(elements, bad_name="없는 이름" if bad["on"] else None)

    monkeypatch.setattr(scene_jobs, "split_scenes", fake)
    dream_id, _ = _ready_dream()

    failed = _job(_request(dream_id).json()["job_id"])

    assert len(calls) == 1
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "LLM_SCHEMA"
    assert _stored_scenes(read_db) == []
    assert client.get(f"/dreams/{dream_id}").json()["status"] == "interviewing"

    bad["on"] = False
    again = _request(dream_id)
    assert again.status_code == 202
    assert again.json()["job_id"] != failed["job_id"]
    assert _job(again.json()["job_id"])["status"] == "succeeded"
    assert len(_stored_scenes(read_db)) == 3


def test_timeout_retries_then_saves_once(monkeypatch, read_db):
    calls: list[int] = []

    def fake(text, answers, elements, complete=None):
        calls.append(1)
        if len(calls) == 1:
            raise LlmTimeoutError("LLM 응답 시간 초과")
        return _split_result(elements)

    monkeypatch.setattr(scene_jobs, "split_scenes", fake)
    dream_id, _ = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert len(calls) == 2
    assert job["status"] == "succeeded"
    assert job["attempt"] == 2
    assert len(_stored_scenes(read_db)) == 3


def test_call_error_stops_after_two_retries(monkeypatch, read_db):
    calls: list[int] = []

    def fake(text, answers, elements, complete=None):
        calls.append(1)
        raise LlmCallError("LLM 호출 실패")

    monkeypatch.setattr(scene_jobs, "split_scenes", fake)
    dream_id, _ = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert len(calls) == 3
    assert job["status"] == "failed"
    assert job["attempt"] == 3
    assert job["error"]["code"] == "PROVIDER_ERROR"
    assert _stored_scenes(read_db) == []
    assert client.get(f"/dreams/{dream_id}").json()["status"] == "interviewing"


def test_schema_error_fails_without_retry(monkeypatch, read_db):
    calls: list[int] = []

    def fake(text, answers, elements, complete=None):
        calls.append(1)
        raise LlmSchemaError("형식 오류")

    monkeypatch.setattr(scene_jobs, "split_scenes", fake)
    dream_id, _ = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert len(calls) == 1
    assert job["status"] == "failed"
    assert job["error"]["code"] == "LLM_SCHEMA"
    assert _stored_scenes(read_db) == []


def test_confidence_rejected_after_scenes_ready(monkeypatch):
    monkeypatch.setattr(
        scene_jobs, "split_scenes", lambda text, answers, elements, complete=None: _split_result(elements)
    )
    dream_id, elements = _ready_dream()
    assert _job(_request(dream_id).json()["job_id"])["status"] == "succeeded"

    res = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": elements[0]["element_id"], "confidence": "low"}]},
    )

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert res.json()["error"]["detail"] == {"status": "images_ready"}


def test_image_jobs_are_committed_with_scenes(monkeypatch, read_db, image_calls):
    """장면 저장 commit 직후 서버가 꺼져 실행이 안 되어도, 이미지 작업 행은 queued로 남는다."""
    started: list[int] = []
    monkeypatch.setattr(runner, "enqueue", lambda job_id, payload=None: started.append(job_id))
    monkeypatch.setattr(
        scene_jobs, "split_scenes", lambda text, answers, elements, complete=None: _split_result(elements)
    )
    dream_id, _ = _ready_dream()

    assert _job(_request(dream_id).json()["job_id"])["status"] == "succeeded"

    image_jobs = [row for row in rows.jobs(read_db) if row.type == JobType.GENERATE_IMAGE.value]
    assert len(image_jobs) == 3
    assert all(row.status == "queued" for row in image_jobs)
    assert sorted(started) == sorted(row.id for row in image_jobs)
    assert image_calls == []
    assert client.get(f"/dreams/{dream_id}").json()["status"] == "scenes_ready"


def test_image_job_row_failure_rolls_back_scenes(monkeypatch, read_db, image_calls):
    """이미지 작업 행을 만들지 못하면 장면 저장과 상태 변경도 함께 되돌린다."""
    original = runner.job_repo.create_job_or_get_active

    def create(db, dream_id, type_, target_id=None):
        if type_ == JobType.GENERATE_IMAGE:
            raise RuntimeError("작업 행 생성 실패")
        return original(db, dream_id, type_, target_id)

    monkeypatch.setattr(runner.job_repo, "create_job_or_get_active", create)
    monkeypatch.setattr(
        scene_jobs, "split_scenes", lambda text, answers, elements, complete=None: _split_result(elements)
    )
    dream_id, _ = _ready_dream()

    job = _job(_request(dream_id).json()["job_id"])

    assert job["status"] == "failed"
    assert job["error"]["code"] == "INTERNAL_ERROR"
    assert _stored_scenes(read_db) == []
    assert [row.type for row in rows.jobs(read_db)] == [JobType.GENERATE_SCENES.value]
    assert image_calls == []
    assert client.get(f"/dreams/{dream_id}").json()["status"] == "interviewing"
