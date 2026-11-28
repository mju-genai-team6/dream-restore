"""장면 목록 GET /dreams/{id}/scenes (C-S3-03).

- 장면 순서대로 현재 버전을 보여 준다. 장면이 아직 없으면 빈 목록
- 요소 확신도는 dream_elements의 현재 값. 요소는 한 요청에서 한 번만 읽는다
- image_url은 이미지가 저장됐을 때만 주고, 끝에 ?v={generated_at}을 붙여 브라우저 캐시를 피한다
"""
from sqlalchemy.orm import Session

from app.core.enums import Confidence, ElementType, JobStatus, JobType
from app.models import DreamElement, Job, SceneVersion
from app.repositories import extractions as extraction_repo
from app.repositories import jobs as job_repo
from app.repositories import scenes as scene_repo
from app.schemas.scenes import SceneElement, SceneItem, SceneListResponse
from app.services.interview import require_dream
from app.services.job_views import job_summary
from app.storage import paths


def image_url(version: SceneVersion) -> str | None:
    if not version.image_path:
        return None
    url = paths.public_url(version.image_path)
    if version.generated_at is None:
        return url
    return f"{url}?v={int(version.generated_at.timestamp())}"


def _elements(version: SceneVersion, elements: dict[int, DreamElement]) -> list[SceneElement]:
    items = []
    for element_id in version.element_ids or []:
        element = elements.get(int(element_id))
        if element is None:
            continue
        items.append(
            SceneElement(
                element_id=element.id,
                name=element.name,
                type=ElementType(element.type),
                confidence=Confidence(element.confidence) if element.confidence else None,
                entity_id=element.entity_id,
            )
        )
    return items


def list_scenes(db: Session, dream_id: int) -> SceneListResponse:
    require_dream(db, dream_id)
    scenes = scene_repo.list_scenes(db, dream_id)
    if not scenes:
        return SceneListResponse(scenes=[])

    elements = {element.id: element for element in extraction_repo.list_elements(db, dream_id)}
    image_jobs: dict[int, Job] = {
        job.target_id: job
        for job in job_repo.get_active_jobs(db, dream_id)
        if job.type == JobType.GENERATE_IMAGE and job.target_id is not None
    }
    items = []
    for scene in scenes:
        version = scene.current_version
        if version is None:
            continue
        active = image_jobs.get(version.id)
        items.append(
            SceneItem(
                scene_id=scene.id,
                order=scene.order,
                summary_ko=version.summary_ko,
                image_url=image_url(version),
                version_no=version.version_no,
                elements=_elements(version, elements),
                status=JobStatus(version.status),
                confidence_level=Confidence(version.confidence_level) if version.confidence_level else None,
                active_job=job_summary(active) if active is not None else None,
                current_version_id=version.id,
            )
        )
    return SceneListResponse(scenes=items)
