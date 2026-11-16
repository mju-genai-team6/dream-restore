"""영상 생성 요청·최신 영상 조회와 render_video 후처리 (E1). 실제 FFmpeg로 작은 영상을 만든다."""
import copy

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.enums import DreamStatus, JobStatus, JobType
from app.main import app
from app.models import Dream, Render, Scene, SceneVersion
from app.repositories import jobs as job_repo
from app.repositories import renders as render_repo
from scripts import seed
from tests.api import rows
from worker.render.video import RenderExecutionError, resolve_ffmpeg_binary

client = TestClient(app)


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    try:
        resolve_ffmpeg_binary()
    except RenderExecutionError as exc:
        pytest.skip(f"FFmpeg가 없어 렌더 API 테스트를 건너뜁니다: {exc}")
    monkeypatch.setattr(settings, "storage_path", tmp_path)  # cached_property
    return tmp_path


def _images_ready_dream(session_factory: sessionmaker[Session], storage, *, scene_confidence=True) -> int:
    """seed의 images_ready 샘플 꿈을 만들고, 장면 원본 이미지 파일을 저장소에 둔다."""
    data = copy.deepcopy(next(d for d in seed.SAMPLE_DREAMS if d["status"] == DreamStatus.IMAGES_READY))
    if not scene_confidence:
        data["scene_confidence"] = [None] * len(data["scenes"])
    with session_factory.begin() as db:
        dream = seed._seed_one(db, 0, data)
        dream_id = dream.id
        for version in _versions(db, dream_id):
            path = storage / version.image_path
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (480, 320), (40 * version.scene_id % 255, 120, 200)).save(path)
    return dream_id


def _versions(db: Session, dream_id: int) -> list[SceneVersion]:
    return list(
        db.scalars(
            select(SceneVersion)
            .join(Scene, Scene.current_version_id == SceneVersion.id)
            .where(Scene.dream_id == dream_id)
            .order_by(Scene.order)
        )
    )


def test_render_creates_video_and_marks_rendered(session_factory, read_db, storage):
    dream_id = _images_ready_dream(session_factory, storage, scene_confidence=False)

    res = client.post(f"/dreams/{dream_id}/renders")  # TestClient는 응답 뒤 작업을 끝까지 실행한다

    assert res.status_code == 202
    body = res.json()
    job = job_repo.get_job(read_db, body["job_id"])
    assert (job.type, job.status, job.target_id, job.stage) == (
        JobType.RENDER_VIDEO, JobStatus.SUCCEEDED, body["render_id"], "verifying"
    )
    render = read_db.get(Render, body["render_id"])
    assert render.status == JobStatus.SUCCEEDED
    assert (render.width, render.height) == (1280, 720)
    assert (storage / render.video_path).stat().st_size > 0
    assert len(render.postprocess_settings["scenes"]) == len(render.scene_version_ids)
    assert read_db.get(Dream, dream_id).status == DreamStatus.RENDERED
    # 비어 있던 장면 확신도 단계가 E1 규칙 결과로 채워진다
    assert all(v.confidence_level in {"high", "medium", "low"} for v in _versions(read_db, dream_id))
    assert not (storage / "tmp" / str(job.id)).exists()

    latest = client.get(f"/dreams/{dream_id}/renders/latest")
    assert latest.status_code == 200
    data = latest.json()
    assert data["render_id"] == body["render_id"]
    assert data["video_url"] == f"/storage/{render.video_path}"
    assert data["is_latest"] is True
    assert len(data["scene_versions"]) == len(render.scene_version_ids)
    assert client.get(f"/dreams/{dream_id}").json()["latest_render"]["render_id"] == body["render_id"]


def test_rendered_dream_can_render_again_and_keeps_existing_confidence(session_factory, read_db, storage):
    dream_id = _images_ready_dream(session_factory, storage)
    before = [v.confidence_level for v in _versions(read_db, dream_id)]

    first = client.post(f"/dreams/{dream_id}/renders").json()
    second = client.post(f"/dreams/{dream_id}/renders").json()

    assert second["render_id"] != first["render_id"]
    read_db.expire_all()
    assert [v.confidence_level for v in _versions(read_db, dream_id)] == before  # 이미 있던 값은 바꾸지 않음
    assert client.get(f"/dreams/{dream_id}/renders/latest").json()["render_id"] == second["render_id"]


def test_render_returns_active_job_instead_of_new_render(session_factory, read_db, storage):
    dream_id = _images_ready_dream(session_factory, storage)
    with session_factory.begin() as db:
        render = render_repo.create_render(db, dream_id)
        render_id = render.id
        job_id = job_repo.create_job_or_get_active(db, dream_id, JobType.RENDER_VIDEO, render_id).id

    res = client.post(f"/dreams/{dream_id}/renders")

    assert res.status_code == 202
    assert res.json() == {"render_id": render_id, "job_id": job_id}
    assert len(list(read_db.scalars(select(Render)))) == 1
    assert [j.id for j in rows.jobs(read_db) if j.type == JobType.RENDER_VIDEO] == [job_id]


def test_render_failure_marks_render_failed(session_factory, read_db, storage):
    dream_id = _images_ready_dream(session_factory, storage)
    with session_factory() as db:
        (storage / _versions(db, dream_id)[0].image_path).unlink()

    body = client.post(f"/dreams/{dream_id}/renders").json()

    job = job_repo.get_job(read_db, body["job_id"])
    assert (job.status, job.error_code) == (JobStatus.FAILED, "INVALID_INPUT")
    assert read_db.get(Render, body["render_id"]).status == JobStatus.FAILED
    assert read_db.get(Dream, dream_id).status == DreamStatus.IMAGES_READY
    assert client.get(f"/dreams/{dream_id}/renders/latest").status_code == 404


def test_render_requires_images_ready(read_db):
    dream_id = client.post("/dreams", json={"input_type": "text", "text": "꿈"}).json()["dream_id"]

    res = client.post(f"/dreams/{dream_id}/renders")

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE"
    assert rows.jobs(read_db) == []


def test_render_not_found():
    assert client.post("/dreams/999/renders").status_code == 404
    assert client.get("/dreams/999/renders/latest").status_code == 404
