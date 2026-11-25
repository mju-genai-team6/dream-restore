"""장면 저장 때 미연결 person·place 요소를 같은 이름의 세계관 항목에 붙인다."""
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.enums import ElementType, FailureCode, JobType
from app.jobs import runner
from app.jobs.context import JobError
from app.jobs.handlers import scenes as scene_jobs
from app.jobs.handlers.images import fake_generate_image
from app.jobs.registry import HANDLERS
from app.llm import client as llm_client
from app.llm.schemas import Scene as LlmScene
from app.llm.schemas import SceneCharacter, SceneSplitResult
from app.main import app
from app.repositories import InvalidData
from app.repositories import extractions as extraction_repo
from app.services import world as world_service
from tests.llm_fakes import FakeLlm

client = TestClient(app)

TEXT = {"input_type": "text", "text": "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다."}
PLAIN_CHARACTER = {"name": "Grandmother", "appearance": "white hair"}
WORLD_LOOK = {"age_range": "40s", "hair": "black bob", "outfit": "red coat", "features": "glasses"}
WORLD_CHARACTER = {**PLAIN_CHARACTER, **WORLD_LOOK}


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client, "openai_complete", fake)
    return fake


@pytest.fixture(autouse=True)
def world_logs(caplog):
    caplog.set_level(logging.INFO, logger="app.services.world")
    return caplog


@pytest.fixture
def pending(monkeypatch) -> list[tuple[int, dict]]:
    """이미지 작업은 스레드로 바로 실행하지 않고 (job_id, payload)만 모은다."""
    queued: list[tuple[int, dict]] = []
    monkeypatch.setattr(
        runner, "enqueue", lambda job_id, payload=None: queued.append((job_id, dict(payload or {})))
    )
    return queued


def _interviewing() -> int:
    dream_id = client.post("/dreams", json=TEXT).json()["dream_id"]
    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]
    for question in questions:
        client.post(f"/dreams/{dream_id}/interview", json={"question_id": question["question_id"], "skipped": True})
    return dream_id


def _elements(dream_id: int) -> dict[str, dict]:
    res = client.get(f"/dreams/{dream_id}/elements")
    assert res.status_code == 200, res.text
    return {item["name"]: item for item in res.json()["elements"]}


def _rename(session_factory, dream_id: int, names: dict[str, str]) -> None:
    with session_factory.begin() as db:
        for element in extraction_repo.list_elements(db, dream_id):
            if element.name in names:
                element.name = names[element.name]


def _preset_link(session_factory, dream_id: int, name: str, entity_id: int) -> None:
    with session_factory.begin() as db:
        element = next(row for row in extraction_repo.list_elements(db, dream_id) if row.name == name)
        extraction_repo.link_element_entity(db, element.id, entity_id)


def _create_entity(**body) -> dict:
    res = client.post("/world/entities", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _prepare(session_factory, names: dict[str, str] | None = None) -> int:
    dream_id = _interviewing()
    elements = _elements(dream_id)
    if names:
        _rename(session_factory, dream_id, names)
        elements = _elements(dream_id)
        assert set(names.values()) <= set(elements)
    saved = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": item["element_id"], "confidence": "high"} for item in elements.values()]},
    )
    assert saved.status_code == 200, saved.text
    return dream_id


def _generate(monkeypatch, dream_id: int) -> None:
    def split(text, answers, elements, complete=None):
        names = [element.name for element in elements]
        return SceneSplitResult(
            scenes=[
                LlmScene(
                    order=order,
                    summary_ko=f"장면 {order}",
                    element_names=list(names),
                    image_prompt_en=f"prompt {order}",
                )
                for order in (1, 2, 3)
            ],
            characters=[
                SceneCharacter(name=element.name, name_en="Grandmother", appearance_en="white hair")
                for element in elements
                if element.type == ElementType.PERSON
            ],
        )

    monkeypatch.setattr(scene_jobs, "split_scenes", split)
    res = client.post(f"/dreams/{dream_id}/jobs", json={"type": "generate_scenes"})
    assert res.status_code == 202, res.text
    job = client.get(f"/jobs/{res.json()['job_id']}")
    assert job.status_code == 200, job.text
    assert job.json()["status"] == "succeeded"
    assert client.get(f"/dreams/{dream_id}").json()["status"] == "scenes_ready"


def _info_messages(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.services.world" and record.levelno == logging.INFO
    ]


def _warning_messages(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.services.world" and record.levelno == logging.WARNING
    ]


def _assert_logs_omit(caplog, *texts: str) -> None:
    for record in caplog.records:
        if record.name != "app.services.world":
            continue
        for text in texts:
            assert text not in record.getMessage()


def test_links_person_and_puts_world_look_in_image_payload(monkeypatch, session_factory, pending, caplog):
    dream_id = _prepare(session_factory, {"할머니": "엄마 "})
    mom = _create_entity(name="엄마", kind="person", **WORLD_LOOK)

    _generate(monkeypatch, dream_id)

    elements = _elements(dream_id)
    assert elements["엄마 "]["entity_id"] == mom["id"]
    assert all(item["entity_id"] is None for name, item in elements.items() if name != "엄마 ")
    scenes = client.get(f"/dreams/{dream_id}/scenes").json()["scenes"]
    assert scenes
    for scene in scenes:
        linked = {item["name"]: item["entity_id"] for item in scene["elements"]}
        assert linked["엄마 "] == mom["id"]
        assert all(entity_id is None for name, entity_id in linked.items() if name != "엄마 ")
    assert len(pending) == 3
    assert all(payload["characters"] == [WORLD_CHARACTER] for _, payload in pending)
    assert _info_messages(caplog) == [f"꿈 {dream_id} 세계관 연결 1건"]
    _assert_logs_omit(caplog, "엄마", TEXT["text"])


def test_links_english_name_ignoring_case_and_space(monkeypatch, session_factory, pending, caplog):
    dream_id = _prepare(session_factory, {"할머니": " MOM "})
    mom = _create_entity(name="Mom", kind="person", hair="black bob")

    _generate(monkeypatch, dream_id)

    assert _elements(dream_id)[" MOM "]["entity_id"] == mom["id"]
    assert _info_messages(caplog) == [f"꿈 {dream_id} 세계관 연결 1건"]
    _assert_logs_omit(caplog, "Mom", "mom", TEXT["text"])
    assert pending


def test_links_place_and_skips_same_name_object(monkeypatch, session_factory, pending, caplog):
    dream_id = _prepare(session_factory)
    sea = _create_entity(name="바다", kind="place")
    _create_entity(name="우산", kind="place")

    _generate(monkeypatch, dream_id)

    elements = _elements(dream_id)
    assert elements["바다"]["type"] == "place"
    assert elements["바다"]["entity_id"] == sea["id"]
    assert elements["우산"]["type"] == "object"
    assert elements["우산"]["entity_id"] is None
    assert elements["학교 복도"]["entity_id"] is None
    assert _info_messages(caplog) == [f"꿈 {dream_id} 세계관 연결 1건"]
    _assert_logs_omit(caplog, "바다", "우산", TEXT["text"])
    assert pending


def test_without_world_entity_payload_stays_name_and_appearance(monkeypatch, session_factory, pending, caplog):
    dream_id = _prepare(session_factory)

    _generate(monkeypatch, dream_id)

    assert all(item["entity_id"] is None for item in _elements(dream_id).values())
    assert len(pending) == 3
    assert all(payload["characters"] == [PLAIN_CHARACTER] for _, payload in pending)
    assert _info_messages(caplog) == [f"꿈 {dream_id} 세계관 연결 0건"]


def test_existing_entity_id_is_kept(monkeypatch, session_factory, pending, caplog):
    dream_id = _prepare(session_factory)
    other = _create_entity(name="다른사람", kind="person", hair="gray")
    _create_entity(name="할머니", kind="person", hair="white bob", outfit="pink cardigan")
    _preset_link(session_factory, dream_id, "할머니", other["id"])

    _generate(monkeypatch, dream_id)

    assert _elements(dream_id)["할머니"]["entity_id"] == other["id"]
    kept = {**PLAIN_CHARACTER, "age_range": None, "hair": "gray", "outfit": None, "features": None}
    assert all(payload["characters"] == [kept] for _, payload in pending)
    assert _info_messages(caplog) == [f"꿈 {dream_id} 세계관 연결 0건"]


def test_link_error_still_saves_scenes(monkeypatch, session_factory, pending, caplog):
    dream_id = _prepare(session_factory)
    _create_entity(name="할머니", kind="person", hair="white bob")

    def boom(db, element_id, entity_id):
        raise InvalidData("세계관 항목을 찾을 수 없습니다.", {"entity_id": entity_id})

    monkeypatch.setattr(world_service.extraction_repo, "link_element_entity", boom)
    _generate(monkeypatch, dream_id)

    assert _elements(dream_id)["할머니"]["entity_id"] is None
    assert len(client.get(f"/dreams/{dream_id}/scenes").json()["scenes"]) == 3
    assert all(payload["characters"] == [PLAIN_CHARACTER] for _, payload in pending)
    warnings = _warning_messages(caplog)
    assert len(warnings) == 1
    assert "할머니" not in warnings[0]
    assert TEXT["text"] not in warnings[0]


def _fail_scene(scene_id: int, error: JobError):
    def handle(ctx, payload):
        if payload["scene_id"] == scene_id:
            raise error
        return fake_generate_image(ctx, payload)

    return handle


def test_retry_payload_includes_world_look(monkeypatch, session_factory, pending):
    dream_id = _prepare(session_factory)
    _create_entity(name="할머니", kind="person", **WORLD_LOOK)
    _generate(monkeypatch, dream_id)
    assert all(payload["characters"] == [WORLD_CHARACTER] for _, payload in pending)

    failed_scene = client.get(f"/dreams/{dream_id}/scenes").json()["scenes"][1]["scene_id"]
    monkeypatch.setitem(
        HANDLERS,
        JobType.GENERATE_IMAGE,
        _fail_scene(failed_scene, JobError(FailureCode.CONTENT_POLICY, "정책 거부")),
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
    assert [payload["characters"] for payload in retried] == [[WORLD_CHARACTER]]
