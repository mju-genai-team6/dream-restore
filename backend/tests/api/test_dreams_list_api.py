"""꿈 일기 목록 GET /dreams (C-S3-05). 실제 DB, 장면·이미지·영상 행은 직접 만든다."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import DreamStatus, JobStatus
from app.main import app
from app.models import Dream, Render, Scene, SceneVersion

client = TestClient(app)

BASE = datetime(2026, 11, 1, tzinfo=UTC)
GENERATED_AT = datetime(2026, 11, 14, 0, 2, tzinfo=UTC)


def _dream(db: Session, days: int, **fields) -> Dream:
    fields.setdefault("input_type", "text")
    dream = Dream(created_at=BASE + timedelta(days=days), **fields)
    db.add(dream)
    db.flush()
    return dream


def _scene(db: Session, dream_id: int, order: int, *, image: bool) -> SceneVersion:
    scene = Scene(dream_id=dream_id, order=order)
    db.add(scene)
    db.flush()
    version = SceneVersion(
        scene_id=scene.id,
        version_no=1,
        summary_ko=f"장면 {order} 요약",
        prompt_en=f"prompt {order}",
        image_path=f"dreams/{dream_id}/scenes/{scene.id}/v1/original.png" if image else None,
        generated_at=GENERATED_AT if image else None,
        status=JobStatus.SUCCEEDED.value if image else JobStatus.QUEUED.value,
    )
    db.add(version)
    db.flush()
    scene.current_version_id = version.id
    db.flush()
    return version


def _list(**params) -> dict:
    res = client.get("/dreams", params=params)
    assert res.status_code == 200, res.text
    assert "X-Mock" not in res.headers
    return res.json()


def test_empty_list():
    assert _list() == {"items": [], "next_cursor": None}


def test_newest_first_and_cursor_pages(session_factory: sessionmaker[Session]):
    with session_factory.begin() as db:
        ids = [_dream(db, days, raw_text=f"꿈 {days}").id for days in range(5)]

    page1 = _list(limit=2)
    page2 = _list(limit=2, cursor=page1["next_cursor"])
    page3 = _list(limit=2, cursor=page2["next_cursor"])

    assert [item["dream_id"] for item in page1["items"]] == [ids[4], ids[3]]
    assert page1["next_cursor"] == str(ids[3])
    assert [item["dream_id"] for item in page2["items"]] == [ids[2], ids[1]]
    assert [item["dream_id"] for item in page3["items"]] == [ids[0]]
    assert page3["next_cursor"] is None


def test_default_limit_is_20(session_factory: sessionmaker[Session]):
    with session_factory.begin() as db:
        for days in range(21):
            _dream(db, days, raw_text="꿈")

    page = _list()

    assert len(page["items"]) == 20
    assert page["next_cursor"] is not None


@pytest.mark.parametrize(
    "params", [{"cursor": "abc"}, {"cursor": "-1"}, {"cursor": "1.5"}, {"limit": 0}, {"limit": 51}]
)
def test_invalid_cursor_or_limit_returns_400(params):
    res = client.get("/dreams", params=params)

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_summary_without_scenes_uses_text_preview(session_factory: sessionmaker[Session]):
    long_text = "가" * 70
    with session_factory.begin() as db:
        raw_only = _dream(db, 0, input_type="voice", raw_text=long_text).id
        confirmed = _dream(db, 1, raw_text="원문", confirmed_text="확정한 짧은 원문").id
        empty = _dream(db, 2, input_type="voice").id

    items = {item["dream_id"]: item for item in _list()["items"]}

    assert items[raw_only]["summary"] == "가" * 60 + "…"
    assert items[raw_only]["input_type"] == "voice"
    assert items[confirmed]["summary"] == "확정한 짧은 원문"
    assert items[empty]["summary"] is None
    for item in items.values():
        assert item["thumbnail_url"] is None
        assert item["has_video"] is False
        assert item["status"] == DreamStatus.RECORDED


def test_first_scene_summary_and_thumbnail(session_factory: sessionmaker[Session]):
    with session_factory.begin() as db:
        dream_id = _dream(db, 0, raw_text="원문").id
        _scene(db, dream_id, 2, image=True)  # 먼저 만들어도 order가 작은 장면이 첫 장면
        _scene(db, dream_id, 1, image=True)
        no_image = _dream(db, 1, raw_text="원문").id
        _scene(db, no_image, 1, image=False)

    items = {item["dream_id"]: item for item in _list()["items"]}
    scenes = client.get(f"/dreams/{dream_id}/scenes").json()["scenes"]

    assert scenes[0]["order"] == 1
    assert items[dream_id]["summary"] == "장면 1 요약"
    assert items[dream_id]["thumbnail_url"] == scenes[0]["image_url"]
    assert items[dream_id]["thumbnail_url"].endswith(f"?v={int(GENERATED_AT.timestamp())}")
    assert items[no_image]["summary"] == "장면 1 요약"
    assert items[no_image]["thumbnail_url"] is None


def test_has_video_only_for_completed_render(session_factory: sessionmaker[Session]):
    with session_factory.begin() as db:
        rendered = _dream(db, 0, raw_text="원문").id
        version = _scene(db, rendered, 1, image=True)
        db.add(
            Render(
                dream_id=rendered,
                scene_version_ids=[version.id],
                status=JobStatus.SUCCEEDED.value,
                video_path=f"dreams/{rendered}/renders/1/video.mp4",
            )
        )
        running = _dream(db, 1, raw_text="원문").id
        version = _scene(db, running, 1, image=True)
        db.add(Render(dream_id=running, scene_version_ids=[version.id], status=JobStatus.RUNNING.value))

    items = {item["dream_id"]: item for item in _list()["items"]}

    assert items[rendered]["has_video"] is True
    assert items[running]["has_video"] is False
