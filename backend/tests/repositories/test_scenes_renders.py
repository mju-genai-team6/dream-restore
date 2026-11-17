import pytest

from app.core.enums import JobStatus
from app.models import SceneVersion
from app.repositories import (
    InvalidData,
    dreams,
    evaluations,
    extractions,
    renders,
    scenes,
    world,
)
from tests.repositories.helpers import (
    ELEMENTS_PAYLOAD,
    SCENES,
    committed_dream,
    run_concurrently,
)


@pytest.fixture
def dream(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    extractions.save_extraction(db, dream.id, "after_interview", ELEMENTS_PAYLOAD, text_length=10)
    return dream


def _finish_images(db, scene_list):
    for scene in scene_list:
        scene.current_version.status = JobStatus.SUCCEEDED.value
        scene.current_version.image_path = f"img/{scene.id}.png"
    db.flush()


def test_create_scenes_with_v1_as_current(db, dream):
    created = scenes.create_scenes(db, dream.id, SCENES)
    assert [s.order for s in created] == [1, 2, 3]
    by_name = {e.name: e.id for e in extractions.list_elements(db, dream.id)}
    v1 = created[1].current_version
    assert v1.version_no == 1 and v1.prompt_en == "grandma" and v1.status == JobStatus.QUEUED
    assert v1.element_ids == [by_name["할머니"], by_name["우산"]]  # 없는 이름은 무시

    listed = scenes.list_scenes(db, dream.id)
    assert [s.current_version.summary_ko for s in listed] == [s["summary_ko"] for s in SCENES]


def test_add_scene_version_numbers_and_keeps_old_rows(db, dream):
    scene = scenes.create_scenes(db, dream.id, SCENES)[0]
    v1 = scene.current_version
    v1_snapshot = (v1.id, v1.prompt_en, v1.summary_ko)

    v2 = scenes.add_scene_version(db, scene.id, summary_ko="수정", prompt_en="hallway v2")
    v3 = scenes.add_scene_version(db, scene.id, summary_ko="재수정", prompt_en="hallway v3")
    assert (v2.version_no, v3.version_no) == (2, 3)
    assert scene.current_version_id == v1.id  # 추가만으로는 현재 버전이 바뀌지 않음

    scenes.set_current_version(db, scene.id, v2.id)
    assert scene.current_version.id == v2.id
    db.expire_all()
    old = db.get(SceneVersion, v1_snapshot[0])
    assert (old.id, old.prompt_en, old.summary_ko) == v1_snapshot


def test_set_current_version_rejects_other_scene(db, dream):
    first, second, _ = scenes.create_scenes(db, dream.id, SCENES)
    with pytest.raises(InvalidData):
        scenes.set_current_version(db, first.id, second.current_version_id)
    assert scenes.set_current_version(db, 999_999_999, first.current_version_id) is None


def test_concurrent_add_scene_version_gets_distinct_numbers(db_engine):
    with committed_dream(db_engine) as dream_id:
        from sqlalchemy.orm import Session

        with Session(db_engine) as s:
            scene_id = scenes.create_scenes(s, dream_id, SCENES[:1])[0].id
            s.commit()
        numbers = run_concurrently(
            db_engine,
            lambda s: scenes.add_scene_version(s, scene_id, summary_ko="s", prompt_en="p").version_no,
            n=4,
        )
        assert sorted(numbers) == [2, 3, 4, 5]


def test_all_images_done(db, dream):
    assert scenes.all_images_done(db, dream.id) is False  # 장면이 없으면 False
    created = scenes.create_scenes(db, dream.id, SCENES)
    assert scenes.all_images_done(db, dream.id) is False
    _finish_images(db, created[:2])
    assert scenes.all_images_done(db, dream.id) is False
    _finish_images(db, created)
    assert scenes.all_images_done(db, dream.id) is True


def test_render_fixes_versions_and_latest_flag(db, dream):
    """완료 기준: 장면 수정 후 기존 버전 행은 남고, 이전 영상의 is_latest는 False."""
    created = scenes.create_scenes(db, dream.id, SCENES)
    assert renders.get_latest_render(db, dream.id) is None

    render = renders.create_render(db, dream.id)
    fixed = [s.current_version_id for s in created]
    assert render.scene_version_ids == fixed and render.status == JobStatus.QUEUED
    assert renders.get_latest_render(db, dream.id) is None  # 완료 전에는 없음

    renders.complete_render(
        db, render.id, video_path="v.mp4", width=1280, height=720, duration=12.0, postprocess_settings={"blur": 1}
    )
    latest = renders.get_latest_render(db, dream.id)
    assert latest.render.id == render.id and latest.is_latest is True
    assert latest.render.video_path == "v.mp4" and latest.render.status == JobStatus.SUCCEEDED

    v2 = scenes.add_scene_version(db, created[0].id, summary_ko="수정", prompt_en="p2")
    scenes.set_current_version(db, created[0].id, v2.id)
    latest = renders.get_latest_render(db, dream.id)
    assert latest.is_latest is False
    assert latest.render.scene_version_ids == fixed  # 고정한 목록은 그대로
    assert db.get(SceneVersion, fixed[0]) is not None  # 기존 버전 행도 그대로


def test_create_render_requires_scenes(db, dream):
    with pytest.raises(InvalidData):
        renders.create_render(db, dream.id)
    assert renders.complete_render(db, 999_999_999, video_path="v", width=1, height=1, duration=1) is None


def test_world_entities_and_evaluations(db, dream):
    entity = world.create_entity(db, name="할머니", kind="person", hair="white")
    assert world.get_entity(db, entity.id) is entity
    assert world.update_entity(db, entity.id, outfit="pink cardigan").outfit == "pink cardigan"
    assert entity.id in [e.id for e in world.list_entities(db, kind="person")]
    with pytest.raises(TypeError):
        world.update_entity(db, entity.id, id=1)

    evaluation = evaluations.save_evaluation(db, dream_id=dream.id, kind="confidence", condition="blur", score=4)
    assert evaluation.id is not None and evaluation.score == 4


def test_fail_render_marks_failed_but_keeps_succeeded(db, dream):
    scenes.create_scenes(db, dream.id, SCENES)
    failed = renders.create_render(db, dream.id)
    assert renders.fail_render(db, failed.id).status == JobStatus.FAILED
    assert renders.get_latest_render(db, dream.id) is None  # 실패한 영상은 최신 영상이 아님

    done = renders.create_render(db, dream.id)
    renders.complete_render(db, done.id, video_path="v.mp4", width=1280, height=720, duration=12.0)
    assert renders.fail_render(db, done.id).status == JobStatus.SUCCEEDED  # 완료된 영상은 덮지 않음
    assert renders.fail_render(db, 999_999_999) is None
