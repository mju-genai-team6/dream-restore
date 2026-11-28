"""자연어로 장면 하나 수정 POST /scenes/{scene_id}/revisions.

설정이 꺼져 있거나 D의 revise_scene이 없으면 409. 호출은 revision_bridge를 요청 시점에 읽는다.
"""
import logging

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import DreamStatus, ElementType, JobType
from app.core.errors import InvalidState, NotFound, ValidationFailed, VersionConflict
from app.jobs import runner
from app.jobs.handlers.images import image_payload
from app.jobs.handlers.narration import narration_payload
from app.llm.schemas import ExtractedElement
from app.llm.schemas import Scene as LlmScene
from app.models import Scene
from app.repositories import dreams as dream_repo
from app.repositories import extractions as extraction_repo
from app.repositories import jobs as job_repo
from app.repositories import scenes as scene_repo
from app.schemas.scenes import SceneRevisionAccepted, SceneRevisionCreate
from app.services import revision_bridge
from app.services.job_views import job_summary
from app.services.llm_calls import call_llm, dream_lock
from app.services.transactions import commit, expire_loaded, rollback

logger = logging.getLogger(__name__)

UNAVAILABLE = "장면 수정 기능을 아직 사용할 수 없습니다."
NOT_READY = "장면 이미지를 만든 뒤에 수정할 수 있습니다."
VERSION_MESSAGE = "지금 보고 있는 장면 버전이 아닙니다."
IN_PROGRESS = "이 장면의 수정을 이미 처리하고 있습니다."
NOT_A_REVISION = "장면을 어떻게 바꿀지 다시 말해 주세요."
LLM_FAILED_MESSAGE = "장면을 수정하지 못했습니다. 다시 시도해 주세요."
MISSING_SCENE = "장면을 찾을 수 없습니다."

_REVISABLE = {DreamStatus.IMAGES_READY, DreamStatus.RENDERED}


def create_revision(
    db: Session,
    scene_id: int,
    body: SceneRevisionCreate,
    background_tasks: BackgroundTasks,
) -> SceneRevisionAccepted:
    """수정 결과를 새 버전으로 저장하고 이미지 작업을 등록한다. 실행은 commit 뒤에 예약한다."""
    revise = revision_bridge.revise_scene
    if not settings.scene_revision_enabled or revise is None:
        raise InvalidState(UNAVAILABLE)
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise NotFound(MISSING_SCENE, {"scene_id": scene_id})

    with dream_lock(scene.dream_id):
        expire_loaded(db)
        scene, current = _ready_scene(db, scene_id, body.base_version_id)
        llm_scene, extracted = _llm_inputs(db, scene, current)
        result = call_llm(
            revise,
            llm_scene,
            body.instruction,
            extracted,
            failed_message=LLM_FAILED_MESSAGE,
        )
        if not result.changed:
            raise ValidationFailed(NOT_A_REVISION, {"field": "instruction", "reason": "not_a_revision"})
        expire_loaded(db)
        scene, _current = _ready_scene(db, scene_id, body.base_version_id)
        try:
            version, image_job, queued = _queue_revision(db, scene, result)
            commit(db)
        except Exception:
            rollback(db)
            raise
    for job_id, payload in queued:
        runner.schedule(background_tasks, job_id, payload)
    return SceneRevisionAccepted(scene_version_id=version.id, job=job_summary(image_job))


def _ready_scene(db: Session, scene_id: int, base_version_id: int):
    """수정할 수 있는 장면과 그 현재 버전. 아니면 404·409."""
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise NotFound(MISSING_SCENE, {"scene_id": scene_id})
    dream = dream_repo.get_dream(db, scene.dream_id)
    if dream is None:
        raise NotFound(MISSING_SCENE, {"scene_id": scene_id})
    if DreamStatus(dream.status) not in _REVISABLE:
        raise InvalidState(NOT_READY, {"status": dream.status})
    if scene.current_version_id != base_version_id:
        raise VersionConflict(VERSION_MESSAGE, {"current_version_id": scene.current_version_id})
    current = scene_repo.get_scene_version(db, base_version_id)
    if current is None or current.scene_id != scene.id:
        raise VersionConflict(VERSION_MESSAGE, {"current_version_id": scene.current_version_id})
    if _revision_in_progress(db, scene):
        raise InvalidState(IN_PROGRESS)
    return scene, current


def _revision_in_progress(db: Session, scene: Scene) -> bool:
    """현재 버전이 아닌 이 장면 버전에 진행 중인 이미지 작업이 있는지."""
    for job in job_repo.get_active_jobs(db, scene.dream_id):
        if job.type != JobType.GENERATE_IMAGE or job.target_id in (None, scene.current_version_id):
            continue
        version = scene_repo.get_scene_version(db, job.target_id)
        if version is not None and version.scene_id == scene.id:
            return True
    return False


def _llm_inputs(db: Session, scene: Scene, current) -> tuple[LlmScene, list[ExtractedElement]]:
    elements = extraction_repo.list_elements(db, scene.dream_id)
    by_id = {element.id: element for element in elements}
    names = [
        by_id[int(element_id)].name
        for element_id in current.element_ids or []
        if int(element_id) in by_id
    ]
    llm_scene = LlmScene(
        order=scene.order,
        summary_ko=current.summary_ko,
        element_names=names,
        image_prompt_en=current.prompt_en,
    )
    extracted = [
        ExtractedElement(type=ElementType(element.type), name=element.name, description=element.description or "")
        for element in elements
    ]
    return llm_scene, extracted


def _queue_revision(db: Session, scene: Scene, result) -> tuple:
    """새 버전과 이미지·나레이션 작업 행을 만든다. commit하지 않는다."""
    elements = extraction_repo.list_elements(db, scene.dream_id)
    ids_by_name = {element.name: element.id for element in elements}
    element_ids = [ids_by_name[name] for name in result.element_names if name in ids_by_name]
    version = scene_repo.add_scene_version(
        db,
        scene.id,
        summary_ko=result.summary_ko,
        prompt_en=result.image_prompt_en,
        element_ids=element_ids,
    )
    characters = scene_repo.list_scene_characters(db, version.id)
    if characters is None:
        logger.warning("장면 %s 버전 %s가 없어 이미지 작업의 인물 목록을 비웁니다.", scene.id, version.id)
        characters = []
    image_job = job_repo.create_job_or_get_active(db, scene.dream_id, JobType.GENERATE_IMAGE, version.id)
    queued = [(image_job.id, image_payload(db, scene.dream_id, version, version.prompt_en, characters))]
    if settings.narration_enabled:
        payload = narration_payload(version)
        if payload is None:
            logger.warning("장면 %s의 나레이션 문장이 없어 나레이션 작업을 등록하지 않습니다.", scene.id)
        else:
            narration = job_repo.create_job_or_get_active(
                db, scene.dream_id, JobType.GENERATE_NARRATION, version.id
            )
            queued.append((narration.id, payload))
    return version, image_job, queued
