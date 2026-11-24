"""장면과 장면 버전 (scenes, scene_versions). 버전은 추가만 하고 기존 행은 바꾸지 않는다."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.enums import ElementType, JobStatus
from app.models import DreamElement, Scene, SceneVersion, WorldEntity
from app.repositories import InvalidData
from app.repositories.extractions import list_elements


def create_scenes(db: Session, dream_id: int, scenes: Sequence[Mapping]) -> list[Scene]:
    """장면과 각 장면의 v1을 만들고 v1을 현재 버전으로 둔다.

    scenes: D의 SceneSplitResult.scenes를 model_dump()한 dict
            ({"order", "summary_ko", "element_names", "image_prompt_en"}).
            장면 확신도를 미리 계산했다면 "confidence_level"을 함께 넣을 수 있다.
    element_names는 이 꿈의 최신 요소 이름으로 찾아 element_ids로 저장한다(없는 이름은 무시).
    """
    ids_by_name = {e.name: e.id for e in list_elements(db, dream_id)}
    created = []
    for item in scenes:
        scene = Scene(dream_id=dream_id, order=item["order"])
        db.add(scene)
        db.flush()
        version = SceneVersion(
            scene_id=scene.id,
            version_no=1,
            summary_ko=item["summary_ko"],
            prompt_en=item["image_prompt_en"],
            element_ids=[ids_by_name[n] for n in item.get("element_names", []) if n in ids_by_name],
            confidence_level=item.get("confidence_level"),
        )
        db.add(version)
        db.flush()
        scene.current_version_id = version.id
        created.append(scene)
    db.flush()
    for scene in created:
        db.refresh(scene, ["current_version"])
    return sorted(created, key=lambda s: s.order)


def add_scene_version(
    db: Session,
    scene_id: int,
    *,
    summary_ko: str,
    prompt_en: str,
    element_ids: Sequence[int] = (),
    confidence_level: str | None = None,
) -> SceneVersion:
    """새 버전을 추가한다. version_no는 (마지막 번호 + 1)로 자동 부여한다.

    현재 버전은 바꾸지 않는다. 이미지 생성이 끝난 뒤 set_current_version으로 바꾼다.
    동시에 두 번 불려도 번호가 겹치지 않도록 장면 행을 잠그고 번호를 정한다.
    """
    db.execute(select(Scene.id).where(Scene.id == scene_id).with_for_update())
    next_no = (db.scalar(select(func.max(SceneVersion.version_no)).where(SceneVersion.scene_id == scene_id)) or 0) + 1
    version = SceneVersion(
        scene_id=scene_id,
        version_no=next_no,
        summary_ko=summary_ko,
        prompt_en=prompt_en,
        element_ids=list(element_ids),
        confidence_level=confidence_level,
    )
    db.add(version)
    db.flush()
    db.refresh(version)
    return version


def set_current_version(db: Session, scene_id: int, version_id: int) -> Scene | None:
    """장면의 현재 버전을 바꾼다. 장면이 없으면 None, 다른 장면의 버전이면 InvalidData."""
    scene = db.get(Scene, scene_id)
    if scene is None:
        return None
    version = db.get(SceneVersion, version_id)
    if version is None or version.scene_id != scene_id:
        raise InvalidData("이 장면의 버전이 아닙니다.", {"scene_id": scene_id, "version_id": version_id})
    scene.current_version_id = version_id
    db.flush()
    db.refresh(scene, ["current_version"])
    return scene


def get_scene_version(db: Session, scene_version_id: int) -> SceneVersion | None:
    return db.get(SceneVersion, scene_version_id)


def save_image_result(
    db: Session,
    scene_version_id: int,
    *,
    final_prompt: str,
    model: str,
    settings: dict,
    seed: int | None,
    image_path: str,
    generated_at: datetime,
    confidence_level: str | None,
) -> bool:
    """이미지 생성 결과를 한 번에 저장하고 status를 succeeded로 바꾼다. 바뀌었으면 True.

    image_path가 비어 있는 버전만 바꾼다 (결과는 한 번만 채움, scene_versions_guard 트리거와 같은 규칙).
    confidence_level은 새 값이 None이 아닐 때만 COALESCE(기존 값, 새 값)으로 저장한다.
    """
    values: dict = {
        "final_prompt": final_prompt,
        "model": model,
        "settings": settings,
        "seed": seed,
        "image_path": image_path,
        "generated_at": generated_at,
        "status": JobStatus.SUCCEEDED.value,
    }
    if confidence_level is not None:
        values["confidence_level"] = func.coalesce(SceneVersion.confidence_level, confidence_level)
    result = db.execute(
        update(SceneVersion)
        .where(SceneVersion.id == scene_version_id, SceneVersion.image_path.is_(None))
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


def mark_scene_version_failed(db: Session, scene_version_id: int) -> bool:
    """이미지가 없고 succeeded가 아닌 버전을 failed로 바꾼다. 바뀌었으면 True."""
    result = db.execute(
        update(SceneVersion)
        .where(
            SceneVersion.id == scene_version_id,
            SceneVersion.image_path.is_(None),
            SceneVersion.status != JobStatus.SUCCEEDED.value,
        )
        .values(status=JobStatus.FAILED.value)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


def reset_failed_scene_version(db: Session, scene_version_id: int) -> bool:
    """이미지 다시 생성 전에 이미지가 없고 failed인 버전을 queued로 되돌린다. 바뀌었으면 True."""
    result = db.execute(
        update(SceneVersion)
        .where(
            SceneVersion.id == scene_version_id,
            SceneVersion.image_path.is_(None),
            SceneVersion.status == JobStatus.FAILED.value,
        )
        .values(status=JobStatus.QUEUED.value)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


def list_scene_characters(db: Session, scene_version_id: int) -> list[dict] | None:
    """장면 버전에 나오는 인물을 E2 generate_image payload의 characters 형식으로 돌려준다 (C 요청).

    [{"name": name_en, "appearance": appearance_en}, ...] — 장면의 element_ids 순서.
    인물(person) 요소 중 name_en이 저장된 것만 (set_character_appearances 전이면 빈 목록).
    세계관 인물에 연결된 요소(entity_id)는 world_entities의 age_range, hair, outfit, features도 함께 준다
    (비어 있는 항목은 None). E2의 from_world_entity가 등록 외형을 먼저, 이 꿈의 appearance를 뒤에 붙인다.
    장면 버전이 없으면 None.
    """
    version = db.get(SceneVersion, scene_version_id)
    if version is None:
        return None
    ids = list(version.element_ids or [])
    if not ids:
        return []
    people = {
        e.id: e
        for e in db.scalars(
            select(DreamElement).where(
                DreamElement.id.in_(ids),
                DreamElement.type == ElementType.PERSON.value,
                DreamElement.name_en.is_not(None),
            )
        )
    }
    entity_ids = {e.entity_id for e in people.values() if e.entity_id is not None}
    entities = (
        {w.id: w for w in db.scalars(select(WorldEntity).where(WorldEntity.id.in_(entity_ids)))} if entity_ids else {}
    )
    result = []
    for i in ids:
        if i not in people:
            continue
        person = people[i]
        item = {"name": person.name_en, "appearance": person.appearance_en}
        entity = entities.get(person.entity_id)
        if entity is not None:
            item.update(age_range=entity.age_range, hair=entity.hair, outfit=entity.outfit, features=entity.features)
        result.append(item)
    return result


def list_scenes(db: Session, dream_id: int) -> list[Scene]:
    """장면 목록 (order 순서). 각 장면의 현재 버전은 scene.current_version으로 읽는다."""
    return list(
        db.scalars(
            select(Scene)
            .where(Scene.dream_id == dream_id)
            .options(selectinload(Scene.current_version))
            .order_by(Scene.order)
        )
    )


def all_images_done(db: Session, dream_id: int) -> bool:
    """장면이 하나 이상 있고, 모든 장면의 현재 버전 이미지 생성이 succeeded이면 True."""
    has_scene = exists().where(Scene.dream_id == dream_id)
    not_done = (
        exists()
        .where(Scene.dream_id == dream_id)
        .where(
            ~exists().where(
                SceneVersion.id == Scene.current_version_id,
                SceneVersion.status == JobStatus.SUCCEEDED.value,
            )
        )
    )
    return bool(db.scalar(select(has_scene & ~not_done)))
