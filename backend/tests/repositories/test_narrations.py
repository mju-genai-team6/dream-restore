import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.models import Dream, Narration, Scene
from app.repositories import InvalidData, dreams, extractions, narrations, scenes
from tests.repositories.helpers import ELEMENTS_PAYLOAD, SCENES

PATH = "dreams/1/scenes/1/v1/narration.mp3"


@pytest.fixture
def version(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    extractions.save_extraction(db, dream.id, "after_interview", ELEMENTS_PAYLOAD, text_length=10)
    return scenes.create_scenes(db, dream.id, SCENES)[0].current_version


def test_add_and_get_narration(db, version):
    assert narrations.get_narration(db, version.id) is None

    narration = narrations.add_narration(db, version.id, audio_path=PATH, duration=3.42)
    assert narration.id is not None
    assert (narration.scene_version_id, narration.audio_path, narration.duration) == (version.id, PATH, 3.42)
    assert narration.created_at is not None
    assert narrations.get_narration(db, version.id).id == narration.id


def test_add_twice_keeps_one_row(db, version):
    first = narrations.add_narration(db, version.id, audio_path=PATH, duration=3.0)
    again = narrations.add_narration(db, version.id, audio_path="other/narration.mp3", duration=9.0)
    assert again.id == first.id
    assert (again.audio_path, again.duration) == (PATH, 3.0)  # 기존 기록을 덮어쓰지 않음


def test_duration_can_be_null(db, version):
    assert narrations.add_narration(db, version.id, audio_path=PATH, duration=None).duration is None


def test_missing_version_is_invalid(db):
    with pytest.raises(InvalidData):
        narrations.add_narration(db, 999_999, audio_path=PATH, duration=1.0)


def test_negative_duration_is_invalid(db, version):
    with pytest.raises(InvalidData):
        narrations.add_narration(db, version.id, audio_path=PATH, duration=-1.0)
    assert narrations.get_narration(db, version.id) is None


@pytest.mark.parametrize("bad", ["/abs/narration.mp3", "C:/x/narration.mp3", "../narration.mp3"])
def test_absolute_path_rejected_by_db(db, version, bad):
    with pytest.raises(IntegrityError), db.begin_nested():
        narrations.add_narration(db, version.id, audio_path=bad, duration=1.0)


def test_deleted_with_dream(db, version):
    narration_id = narrations.add_narration(db, version.id, audio_path=PATH, duration=1.0).id
    scene = db.get(Scene, version.scene_id)
    db.execute(delete(Dream).where(Dream.id == scene.dream_id))  # DB의 ON DELETE CASCADE로 지워지는지 본다
    db.flush()
    db.expire_all()
    assert db.scalar(select(Narration).where(Narration.id == narration_id)) is None
