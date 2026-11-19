"""텍스트 꿈 기록부터 영상 조회까지 전체 흐름 (C-S3-07 준비).

LLM은 가짜 응답(FakeLlm, 가짜 split_scenes), 이미지는 conftest의 가짜 핸들러를 쓴다.
STT는 텍스트 입력이라 불리지 않아야 하므로 불리면 실패하게 바꾼다. 영상은 실제 FFmpeg로 만든다.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.enums import ElementType
from app.jobs import runner
from app.jobs.handlers import scenes as scene_jobs
from app.llm import client as llm_client
from app.llm.schemas import Scene as LlmScene
from app.llm.schemas import SceneCharacter, SceneSplitResult
from app.main import app
from app.services import dreams as dream_service
from tests.llm_fakes import FakeLlm
from worker.render.video import RenderExecutionError, resolve_ffmpeg_binary

client = TestClient(app)

TEXT = "어두운 학교 복도에서 할머니가 노란 우산을 건네줬다. 창밖은 회색 바다였다."


@pytest.fixture(autouse=True)
def ffmpeg_required() -> None:
    try:
        resolve_ffmpeg_binary()
    except RenderExecutionError as exc:
        pytest.skip(f"FFmpeg가 없어 전체 흐름 테스트를 건너뜁니다: {exc}")


@pytest.fixture(autouse=True)
def no_real_ai(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "openai_complete", FakeLlm())

    def no_stt(*_args, **_kwargs):
        raise AssertionError("텍스트 입력 흐름에서 STT가 불렸습니다.")

    monkeypatch.setattr(dream_service, "transcribe", no_stt)

    def split(text, answers, elements, complete=None):
        names = [element.name for element in elements]
        return SceneSplitResult(
            scenes=[
                LlmScene(order=order, summary_ko=f"장면 {order}", element_names=names, image_prompt_en=f"prompt {order}")
                for order in (1, 2, 3)
            ],
            characters=[
                SceneCharacter(name=element.name, name_en="Grandmother", appearance_en="white hair")
                for element in elements
                if element.type == ElementType.PERSON
            ],
        )

    monkeypatch.setattr(scene_jobs, "split_scenes", split)
    # 장면 생성 성공 뒤 이미지 작업을 같은 스레드에서 바로 실행한다
    monkeypatch.setattr(runner, "enqueue", runner.run_job)


def _status(dream_id: int) -> str:
    return client.get(f"/dreams/{dream_id}").json()["status"]


def test_text_dream_to_rendered_video():
    res = client.post("/dreams", json={"input_type": "text", "text": TEXT})
    assert res.status_code == 201, res.text
    dream_id = res.json()["dream_id"]

    questions = client.get(f"/dreams/{dream_id}/interview").json()["questions"]
    assert 5 <= len(questions) <= 7
    first, *rest = questions
    answer = client.post(
        f"/dreams/{dream_id}/interview",
        json={"question_id": first["question_id"], "answer": "형광등이 깜빡였어요"},
    )
    assert answer.status_code == 200, answer.text
    for question in rest:
        client.post(f"/dreams/{dream_id}/interview", json={"question_id": question["question_id"], "skipped": True})
    assert _status(dream_id) == "interviewing"

    elements = client.get(f"/dreams/{dream_id}/elements").json()["elements"]
    assert elements
    confidence = {e["element_id"]: "low" if e["type"] == ElementType.EMOTION else "high" for e in elements}
    saved = client.put(
        f"/dreams/{dream_id}/elements/confidence",
        json={"items": [{"element_id": eid, "confidence": value} for eid, value in confidence.items()]},
    )
    assert saved.status_code == 200, saved.text

    job = client.post(f"/dreams/{dream_id}/jobs", json={"type": "generate_scenes"})
    assert job.status_code == 202, job.text
    assert client.get(f"/jobs/{job.json()['job_id']}").json()["status"] == "succeeded"
    assert _status(dream_id) == "images_ready"

    render = client.post(f"/dreams/{dream_id}/renders")  # TestClient는 응답 뒤 작업을 끝까지 실행한다
    assert render.status_code == 202, render.text
    assert client.get(f"/jobs/{render.json()['job_id']}").json()["status"] == "succeeded"
    assert _status(dream_id) == "rendered"

    scenes = client.get(f"/dreams/{dream_id}/scenes").json()["scenes"]
    assert [scene["order"] for scene in scenes] == [1, 2, 3]
    for scene in scenes:
        assert scene["status"] == "succeeded"
        assert scene["image_url"].startswith(f"/storage/dreams/{dream_id}/scenes/{scene['scene_id']}/v1/original.png?v=")
        assert scene["confidence_level"] == "high"
        assert scene["active_job"] is None
        assert {e["element_id"]: e["confidence"] for e in scene["elements"]} == confidence

    latest = client.get(f"/dreams/{dream_id}/renders/latest")
    assert latest.status_code == 200, latest.text
    data = latest.json()
    assert data["render_id"] == render.json()["render_id"]
    assert data["is_latest"] is True
    assert data["video_url"] == f"/storage/dreams/{dream_id}/renders/{data['render_id']}/video.mp4"
    assert [(v["scene_id"], v["version_no"]) for v in data["scene_versions"]] == [
        (scene["scene_id"], scene["version_no"]) for scene in scenes
    ]
