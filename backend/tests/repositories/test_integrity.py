"""이관 문서 5장 무결성 규칙을 DB가 직접 막는지 확인한다 (함수를 거치지 않고 ORM으로 바로 고쳐 본다)."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.enums import JobStatus
from app.repositories import audio, dreams, evaluations, extractions, renders, scenes
from tests.repositories.helpers import ELEMENTS_PAYLOAD, SCENES


@pytest.fixture
def scene_list(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    extractions.save_extraction(db, dream.id, "after_interview", ELEMENTS_PAYLOAD, text_length=10)
    return scenes.create_scenes(db, dream.id, SCENES)


def _expect_rejected(db, change) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        change()
        db.flush()
    db.expire_all()


# --- 장면 버전은 추가만 -------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [("summary_ko", "몰래 수정"), ("prompt_en", "edited"), ("version_no", 9), ("element_ids", [1])],
)
def test_scene_version_content_cannot_change(db, scene_list, column, value):
    version = scene_list[0].current_version
    _expect_rejected(db, lambda: setattr(version, column, value))


def test_scene_version_generation_result_fills_once(db, scene_list):
    version = scene_list[0].current_version
    # 처음 채우기와 상태 변경은 허용
    version.status = JobStatus.RUNNING.value
    version.final_prompt = "hallway, grandma in pink cardigan"
    version.model = "gpt-image-1"
    version.settings = {"size": "1536x1024"}
    version.seed = 42
    version.image_path = "dreams/1/scenes/1/v1/original.png"
    version.confidence_level = "medium"
    version.status = JobStatus.SUCCEEDED.value
    db.flush()

    for column, value in [
        ("image_path", "dreams/1/scenes/1/v1/other.png"),
        ("final_prompt", "changed"),
        ("model", "other-model"),
        ("seed", 7),
        ("settings", {"size": "1024x1024"}),
        ("confidence_level", "low"),
    ]:
        _expect_rejected(db, lambda c=column, v=value: setattr(version, c, v))


def test_scene_version_status_can_change(db, scene_list):
    version = scene_list[0].current_version
    version.status = JobStatus.FAILED.value
    db.flush()
    version.status = JobStatus.QUEUED.value  # 재시도
    db.flush()


def test_scene_current_version_can_change(db, scene_list):
    scene = scene_list[0]
    v2 = scenes.add_scene_version(db, scene.id, summary_ko="수정", prompt_en="p2")
    scenes.set_current_version(db, scene.id, v2.id)  # 장면 쪽은 바꿀 수 있다


# --- 영상의 장면 버전 고정 ----------------------------------------------------


def test_render_scene_versions_cannot_change(db, scene_list):
    render = renders.create_render(db, scene_list[0].dream_id)
    _expect_rejected(db, lambda: setattr(render, "scene_version_ids", [scene_list[0].current_version_id]))
    # 결과 저장은 그대로 된다
    renders.complete_render(db, render.id, video_path="dreams/1/renders/1/video.mp4", width=1280, height=720, duration=9)


# --- 파일과 기록 구분 (상대 경로만) -------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    ["/abs/dreams/1/audio/1.webm", "\\dreams\\1.webm", "C:/storage/1.webm", "c:\\storage\\1.webm", "dreams/../../etc/passwd"],
)
def test_absolute_or_escaping_paths_rejected(db, bad_path):
    dream = dreams.create_dream(db, input_type="voice", raw_text=None)
    with pytest.raises(IntegrityError), db.begin_nested():
        audio.add_audio_file(db, dream_id=dream.id, path=bad_path, mime_type="audio/webm", size=1, duration=None)


def test_relative_path_allowed(db):
    dream = dreams.create_dream(db, input_type="voice", raw_text=None)
    row = audio.add_audio_file(
        db, dream_id=dream.id, path=f"dreams/{dream.id}/audio/1.webm", mime_type="audio/webm", size=1, duration=None
    )
    assert row.id is not None


def test_image_path_must_be_relative(db, scene_list):
    version = scene_list[0].current_version
    _expect_rejected(db, lambda: setattr(version, "image_path", "/tmp/original.png"))


# --- 평가 종류는 지표 뷰가 읽는 값만 -----------------------------------------


@pytest.mark.parametrize("kind", ["confidence", "character"])
def test_evaluation_kind_allowed(db, kind):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    assert evaluations.save_evaluation(db, dream_id=dream.id, kind=kind, condition="A", score=3).id is not None


def test_unknown_evaluation_kind_rejected(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    with pytest.raises(IntegrityError), db.begin_nested():
        evaluations.save_evaluation(db, dream_id=dream.id, kind="consistency", condition="A", score=3)
