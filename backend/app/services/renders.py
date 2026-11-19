"""영상 생성 요청·최신 영상 조회와 render_video 작업 후처리 (E1).

- 요청: images_ready·rendered 꿈에서 장면 버전을 고정한 렌더 행을 만들고 render_video 작업을 등록한다.
  진행 중인 렌더 작업이 있으면 새 렌더를 만들지 않고 그 작업을 돌려준다 (버튼 연타 대비).
- 성공 후처리: 렌더 결과 저장, 장면 버전의 장면 확신도 단계 기록(비어 있을 때만), 꿈 상태 rendered.
- 실패 후처리: 렌더 행을 failed로.
"""
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import DreamStatus, ElementType, JobType
from app.core.errors import InvalidState, NotFound
from app.jobs.registry import on_failure, on_success
from app.jobs.submit import submit_job
from app.models import DreamElement, Job, Render, SceneVersion
from app.repositories import InvalidData
from app.repositories import dreams as dream_repo
from app.repositories import jobs as job_repo
from app.repositories import renders as render_repo
from app.repositories import scenes as scene_repo
from app.schemas.renders import RenderCreateResponse, RenderResponse, SceneVersionRef
from app.services.interview import require_dream
from app.services.llm_calls import dream_lock
from app.services.state_machine import ensure_transition
from app.services.transactions import commit, expire_loaded, rollback
from app.storage import paths

_RENDERABLE = {DreamStatus.IMAGES_READY, DreamStatus.RENDERED}


def _active_render_job(db: Session, dream_id: int) -> Job | None:
    return next((j for j in job_repo.get_active_jobs(db, dream_id) if j.type == JobType.RENDER_VIDEO), None)


def _scene_payload(db: Session, render: Render) -> list[dict]:
    """고정된 장면 버전 순서대로 E1 render_video 입력을 만든다 (worker/render/handler.py)."""
    versions = [scene_repo.get_scene_version(db, vid) for vid in render.scene_version_ids]
    element_ids = {eid for v in versions if v for eid in v.element_ids}
    elements = {e.id: e for e in db.scalars(select(DreamElement).where(DreamElement.id.in_(element_ids)))}
    scenes = []
    for order, version in enumerate(versions, start=1):
        if version is None or not version.image_path:
            raise InvalidState("이미지가 없는 장면이 있습니다.", {"render_id": render.id})
        item = {
            "scene_id": version.scene_id,
            "version_no": version.version_no,
            "order": order,
            "scene_version_id": version.id,
            "image_path": str(settings.storage_path / version.image_path),
            # 감정은 블러 계산에서 빠지므로 확신도가 비어 있어도 렌더를 막지 않는다. 시각 요소 누락은 E1이 INVALID_INPUT
            "elements": [
                {"id": e.id, "type": e.type, "name": e.name, "confidence": e.confidence}
                for eid in version.element_ids
                if (e := elements.get(eid)) is not None
                and not (e.type == ElementType.EMOTION and e.confidence is None)
            ],
        }
        if not item["elements"] and version.confidence_level:
            item["confidence_level"] = version.confidence_level
        scenes.append(item)
    return scenes


def create_render(db: Session, dream_id: int, background_tasks: BackgroundTasks) -> RenderCreateResponse:
    with dream_lock(dream_id):
        expire_loaded(db)
        dream = require_dream(db, dream_id)
        if DreamStatus(dream.status) not in _RENDERABLE:
            raise InvalidState("장면 이미지가 모두 준비된 뒤에 영상을 만들 수 있습니다.", {"status": dream.status})
        if (active := _active_render_job(db, dream_id)) is not None:
            return RenderCreateResponse(render_id=active.target_id, job_id=active.id)
        if not scene_repo.all_images_done(db, dream_id):
            raise InvalidState("아직 이미지가 준비되지 않은 장면이 있습니다.", {"status": dream.status})
        try:
            render = render_repo.create_render(db, dream_id)
            payload = {"render_id": render.id, "expected_scene_count": len(render.scene_version_ids),
                       "scenes": _scene_payload(db, render)}
            commit(db)
        except InvalidData as exc:
            rollback(db)
            raise InvalidState(exc.message, exc.detail) from exc
        except Exception:
            rollback(db)
            raise
        job, _created = submit_job(
            db,
            background_tasks,
            dream_id=dream_id,
            job_type=JobType.RENDER_VIDEO,
            target_id=render.id,
            payload=payload,
        )
    return RenderCreateResponse(render_id=render.id, job_id=job.id)


def get_latest_render(db: Session, dream_id: int) -> RenderResponse:
    """검증까지 끝나 succeeded인 영상만 준다."""
    require_dream(db, dream_id)
    latest = render_repo.get_latest_render(db, dream_id)
    if latest is None or latest.render.video_path is None:
        raise NotFound("아직 완성된 영상이 없습니다.", {"dream_id": dream_id})
    refs = []
    for vid in latest.render.scene_version_ids:
        version = scene_repo.get_scene_version(db, vid)
        if version is not None:
            refs.append(SceneVersionRef(scene_id=version.scene_id, version_no=version.version_no))
    return RenderResponse(
        render_id=latest.render.id,
        video_url=paths.public_url(latest.render.video_path),
        scene_versions=refs,
        is_latest=latest.is_latest,
        created_at=latest.render.created_at,
    )


@on_success(JobType.RENDER_VIDEO)
def save_render(db: Session, job: Job, result: dict) -> None:
    """실행기가 이 함수 뒤에 succeeded와 함께 commit한다. 여기서 commit하지 않는다."""
    render = render_repo.complete_render(
        db,
        job.target_id,
        video_path=result["video_path"],
        width=result["width"],
        height=result["height"],
        duration=result["duration"],
        postprocess_settings={**result.get("postprocess_settings", {}), "scenes": result.get("scenes", [])},
    )
    if render is None:
        raise RuntimeError(f"렌더 {job.target_id}가 없습니다.")

    # scene_versions.confidence_level은 NULL일 때 한 번만 채울 수 있다 (DB 트리거). 이미 있으면 그대로 둔다
    for scene in result.get("scenes", []):
        version = db.get(SceneVersion, scene.get("scene_version_id"))
        if version is not None and version.confidence_level is None:
            version.confidence_level = scene["confidence_level"]

    dream = dream_repo.get_dream(db, job.dream_id)
    if dream is not None and DreamStatus(dream.status) == DreamStatus.IMAGES_READY:
        ensure_transition(DreamStatus.IMAGES_READY, DreamStatus.RENDERED)
        if not dream_repo.transition_status(db, job.dream_id, DreamStatus.IMAGES_READY, DreamStatus.RENDERED):
            raise InvalidState("꿈 상태를 바꾸지 못했습니다.", {"dream_id": job.dream_id})
    db.flush()


@on_failure(JobType.RENDER_VIDEO)
def mark_render_failed(db: Session, job: Job, error_code: str | None, error_message: str) -> None:
    if job.target_id:
        render_repo.fail_render(db, job.target_id)
