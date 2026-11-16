"""C 요청으로 추가한 함수 (DB요청사항 1-2)."""

from app.core.enums import JobStatus, JobType
from app.repositories import dreams, extractions, jobs, scenes
from tests.repositories.helpers import ELEMENTS_PAYLOAD, SCENES


def test_update_raw_text(db):
    dream = dreams.create_dream(db, input_type="voice", raw_text=None)
    updated = dreams.update_raw_text(db, dream.id, "STT 변환 결과")
    assert updated is dream and dream.raw_text == "STT 변환 결과"
    assert dreams.update_raw_text(db, 999_999_999, "x") is None


def test_update_confirmed_text_can_clear(db):
    """다시 녹음할 때 확정 원문을 비운다."""
    dream = dreams.create_dream(db, input_type="voice", raw_text="처음 녹음")
    dreams.update_confirmed_text(db, dream.id, "처음 녹음")
    cleared = dreams.update_confirmed_text(db, dream.id, None)
    assert cleared.confirmed_text is None
    db.expire_all()
    assert dreams.get_dream(db, dream.id).confirmed_text is None


def test_get_latest_extraction(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    assert extractions.get_latest_extraction(db, dream.id) is None

    raw = extractions.save_extraction(db, dream.id, "raw", ELEMENTS_PAYLOAD, text_length=10)
    assert extractions.get_latest_extraction(db, dream.id).id == raw.id

    after = extractions.save_extraction(db, dream.id, "after_interview", {"elements": []}, text_length=20)
    assert extractions.get_latest_extraction(db, dream.id).id == after.id
    assert extractions.get_latest_extraction(db, dream.id, phase="raw").id == raw.id
    # list_elements와 같은 추출을 본다
    assert extractions.list_elements(db, dream.id) == []


def test_get_active_jobs(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    other = dreams.create_dream(db, input_type="text", raw_text="다른 꿈")
    assert jobs.get_active_jobs(db, dream.id) == []

    scenes_job = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_SCENES)
    image_job = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=1)
    done = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, target_id=2)
    jobs.update_job(db, image_job.id, status=JobStatus.RUNNING)
    jobs.update_job(db, done.id, status=JobStatus.SUCCEEDED)
    jobs.create_job_or_get_active(db, other.id, JobType.GENERATE_SCENES)

    assert [j.id for j in jobs.get_active_jobs(db, dream.id)] == [scenes_job.id, image_job.id]


def test_get_scene_version(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    extractions.save_extraction(db, dream.id, "after_interview", ELEMENTS_PAYLOAD, text_length=10)
    scene = scenes.create_scenes(db, dream.id, SCENES)[0]
    version = scenes.get_scene_version(db, scene.current_version_id)
    assert version.scene_id == scene.id and version.version_no == 1
    assert scenes.get_scene_version(db, 999_999_999) is None
