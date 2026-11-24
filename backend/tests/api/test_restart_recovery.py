"""render_video가 서버 재시작으로 중단된 뒤의 상태와 다시 요청 (C-S4-01). 다시 요청은 실제 FFmpeg로 만든다.

generate_scenes·generate_image의 재시작 복구는 test_generate_scenes.py·test_generate_image.py에 있다.
"""
import copy

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.enums import DreamStatus, JobStatus, JobType
from app.jobs import runner
from app.main import app
from app.models import Dream, Render, Scene, SceneVersion
from app.repositories import jobs as job_repo
from app.repositories import renders as render_repo
from scripts import seed
from worker.render.video import RenderExecutionError, resolve_ffmpeg_binary

client = TestClient(app)


@pytest.fixture(autouse=True)
def ffmpeg():
    try:
        resolve_ffmpeg_binary()
    except RenderExecutionError as exc:
        pytest.skip(f"FFmpeg가 없어 렌더 재시작 테스트를 건너뜁니다: {exc}")


def _images_ready_dream(session_factory: sessionmaker[Session]) -> int:
    """seed의 images_ready 샘플 꿈을 만들고 장면 원본 이미지 파일을 저장소에 둔다."""
    data = copy.deepcopy(next(d for d in seed.SAMPLE_DREAMS if d["status"] == DreamStatus.IMAGES_READY))
    with session_factory.begin() as db:
        dream_id = seed._seed_one(db, 0, data).id
        versions = db.scalars(
            select(SceneVersion)
            .join(Scene, Scene.current_version_id == SceneVersion.id)
            .where(Scene.dream_id == dream_id)
        )
        for version in versions:
            path = settings.storage_path / version.image_path
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (480, 320), (40 * version.scene_id % 255, 120, 200)).save(path)
    return dream_id


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_interrupted_render_fails_render_and_can_request_again(
    session_factory: sessionmaker[Session], read_db: Session, status: JobStatus
):
    dream_id = _images_ready_dream(session_factory)
    with session_factory.begin() as db:
        render_id = render_repo.create_render(db, dream_id).id
        job_id = job_repo.create_job_or_get_active(db, dream_id, JobType.RENDER_VIDEO, render_id).id
        if status == JobStatus.RUNNING:
            assert job_repo.claim_job(db, job_id)

    assert runner.recover_interrupted() == 1

    job = client.get(f"/jobs/{job_id}").json()
    assert (job["status"], job["error"]["code"]) == ("failed", "INTERRUPTED")
    assert read_db.get(Render, render_id).status == JobStatus.FAILED
    dream = client.get(f"/dreams/{dream_id}").json()
    assert (dream["status"], dream["active_job"], dream["latest_render"]) == ("images_ready", None, None)
    assert client.get(f"/dreams/{dream_id}/renders/latest").status_code == 404

    res = client.post(f"/dreams/{dream_id}/renders")

    assert res.status_code == 202, res.text
    assert res.json()["render_id"] != render_id
    assert client.get(f"/jobs/{res.json()['job_id']}").json()["status"] == "succeeded"
    read_db.expire_all()
    assert read_db.get(Dream, dream_id).status == DreamStatus.RENDERED
    assert client.get(f"/dreams/{dream_id}/renders/latest").json()["render_id"] == res.json()["render_id"]
