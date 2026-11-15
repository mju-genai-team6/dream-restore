"""모델·마이그레이션 제약 테스트 (C2). 이관 문서 2장 표의 제약이 실제 DB에 걸려 있는지 확인한다."""

from enum import StrEnum

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.enums import (
    Confidence,
    DreamStatus,
    ElementType,
    ExtractionPhase,
    FailureCode,
    InputType,
    JobStage,
    JobStatus,
    JobType,
)
from app.models import (
    AudioFile,
    Dream,
    DreamElement,
    Extraction,
    InterviewQuestion,
    Job,
    Render,
    Scene,
    SceneVersion,
)


def _dream(db, **kw) -> Dream:
    dream = Dream(input_type="text", raw_text="꿈 원문", **kw)
    db.add(dream)
    db.flush()
    return dream


def _scene_with_version(db, dream: Dream) -> tuple[Scene, SceneVersion]:
    scene = Scene(dream_id=dream.id, order=1)
    db.add(scene)
    db.flush()
    version = SceneVersion(scene_id=scene.id, version_no=1, summary_ko="요약", prompt_en="prompt")
    db.add(version)
    db.flush()
    scene.current_version_id = version.id
    db.flush()
    return scene, version


def _expect_integrity_error(db, obj) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(obj)
        db.flush()


# DB의 CHECK 제약과 app/core/enums.py 값이 같은지 (마이그레이션이 enums.py와 어긋나면 실패)
ENUM_CHECKS: list[tuple[str, str, type[StrEnum]]] = [
    ("dreams", "input_type", InputType),
    ("dreams", "status", DreamStatus),
    ("extractions", "phase", ExtractionPhase),
    ("dream_elements", "type", ElementType),
    ("dream_elements", "confidence", Confidence),
    ("scene_versions", "confidence_level", Confidence),
    ("scene_versions", "status", JobStatus),
    ("renders", "status", JobStatus),
    ("jobs", "type", JobType),
    ("jobs", "status", JobStatus),
    ("jobs", "stage", JobStage),
    ("jobs", "error_code", FailureCode),
]


@pytest.mark.parametrize(("table", "column", "enum_cls"), ENUM_CHECKS, ids=lambda v: getattr(v, "__name__", v))
def test_check_constraint_matches_enums(db, table, column, enum_cls):
    definition = db.scalar(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
        {"name": f"ck_{table}_{column}"},
    )
    assert definition is not None, f"ck_{table}_{column} 제약이 없습니다"
    allowed = {part.split("'")[1] for part in definition.split("ARRAY[")[1].split(",")}
    assert allowed == {member.value for member in enum_cls}


def test_new_dream_defaults(db):
    dream = _dream(db)
    db.refresh(dream)
    assert dream.status == DreamStatus.RECORDED
    assert dream.created_at is not None and dream.updated_at is not None


def test_invalid_status_rejected(db):
    _expect_integrity_error(db, Dream(input_type="text", status="done"))


def test_invalid_audio_mime_rejected(db):
    dream = _dream(db)
    _expect_integrity_error(db, AudioFile(dream_id=dream.id, path="a.ogg", mime_type="audio/ogg", size=1))


def test_confidence_allows_null_but_not_unknown_value(db):
    dream = _dream(db)
    extraction = Extraction(dream_id=dream.id, phase="raw", payload={}, element_count=1, text_length=4)
    db.add(extraction)
    db.flush()
    db.add(DreamElement(dream_id=dream.id, extraction_id=extraction.id, type="person", name="할머니"))
    db.flush()  # 확신도 입력 전에는 NULL 허용
    _expect_integrity_error(
        db, DreamElement(dream_id=dream.id, extraction_id=extraction.id, type="person", name="엄마", confidence="sure")
    )


def test_interview_question_order_unique_per_dream(db):
    dream = _dream(db)
    db.add(InterviewQuestion(dream_id=dream.id, order=1, text="첫 질문"))
    db.flush()
    _expect_integrity_error(db, InterviewQuestion(dream_id=dream.id, order=1, text="같은 순서"))


def test_scene_version_no_unique_per_scene(db):
    dream = _dream(db)
    scene, _ = _scene_with_version(db, dream)
    _expect_integrity_error(db, SceneVersion(scene_id=scene.id, version_no=1, summary_ko="s", prompt_en="p"))


def test_active_job_is_unique_per_dream_type_target(db):
    dream = _dream(db)
    first = Job(dream_id=dream.id, type=JobType.GENERATE_SCENES)  # target_id NULL
    db.add(first)
    db.flush()
    # target_id가 NULL이어도 같은 작업으로 본다 (NULLS NOT DISTINCT)
    _expect_integrity_error(db, Job(dream_id=dream.id, type=JobType.GENERATE_SCENES))

    # 끝난 작업은 제약 대상이 아니므로 다시 만들 수 있다
    first.status = JobStatus.FAILED
    db.flush()
    db.add(Job(dream_id=dream.id, type=JobType.GENERATE_SCENES))
    db.flush()

    # 대상이 다르면 동시에 진행 가능 (장면별 이미지 생성)
    db.add_all([
        Job(dream_id=dream.id, type=JobType.GENERATE_IMAGE, target_id=1),
        Job(dream_id=dream.id, type=JobType.GENERATE_IMAGE, target_id=2),
    ])
    db.flush()


def test_deleting_dream_cascades_to_children(db):
    dream = _dream(db)
    extraction = Extraction(dream_id=dream.id, phase="raw", payload={"elements": []}, element_count=0, text_length=4)
    db.add_all([
        AudioFile(dream_id=dream.id, path="dreams/1/audio/1.webm", mime_type="audio/webm", size=10),
        extraction,
        InterviewQuestion(dream_id=dream.id, order=1, text="q"),
        Job(dream_id=dream.id, type=JobType.GENERATE_SCENES),
    ])
    db.flush()
    db.add(DreamElement(dream_id=dream.id, extraction_id=extraction.id, type="place", name="바다"))
    _, version = _scene_with_version(db, dream)
    db.add(Render(dream_id=dream.id, scene_version_ids=[version.id]))
    db.flush()

    db.delete(dream)
    db.flush()
    db.expunge_all()

    for model in (AudioFile, Extraction, DreamElement, InterviewQuestion, Job, Scene, SceneVersion, Render):
        assert db.scalar(select(func.count()).select_from(model)) == 0, model.__tablename__
