"""generate_scenes 작업. 핸들러는 split_scenes만 부르고, 저장은 성공 후처리에서 한다."""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import DreamStatus, FailureCode, JobStage, JobType
from app.core.errors import InvalidState
from app.jobs.context import JobContext, JobError
from app.jobs.handlers.images import image_payload
from app.jobs.handlers.narration import narration_payload
from app.jobs.registry import FollowUp, on_success, register
from app.llm.client import LlmCallError, LlmSchemaError, LlmTimeoutError
from app.llm.scenes import split_scenes
from app.llm.schemas import ExtractedElement, InterviewAnswer
from app.models.job import Job
from app.repositories import InvalidData
from app.repositories import dreams as dream_repo
from app.repositories import extractions as extraction_repo
from app.repositories import scenes as scene_repo
from app.services import world as world_service
from app.services.state_machine import ensure_transition

logger = logging.getLogger(__name__)

SCHEMA_MESSAGE = "장면을 만들지 못했습니다. 다시 시도해 주세요."
CALL_MESSAGE = "장면을 만들지 못했습니다. 다시 시도해 주세요."
TIMEOUT_MESSAGE = "AI 응답이 늦어지고 있습니다. 잠시 후 다시 시도해 주세요."
STATE_MESSAGE = "꿈 상태를 바꾸지 못했습니다."


@register(JobType.GENERATE_SCENES)
def handle_generate_scenes(ctx: JobContext, payload: dict) -> dict:
    """요청 때 실어 둔 원문·답변·요소로 장면을 나눈다. DB는 읽지 않는다."""
    ctx.report_stage(JobStage.SPLITTING)
    answers = [InterviewAnswer(question=item["question"], answer=item.get("answer")) for item in payload["answers"]]
    elements = [
        ExtractedElement(type=item["type"], name=item["name"], description=item.get("description") or "")
        for item in payload["elements"]
    ]
    try:
        result = split_scenes(payload["text"], answers, elements)
    except LlmTimeoutError as exc:
        raise JobError(FailureCode.TIMEOUT, TIMEOUT_MESSAGE, retryable=True) from exc
    except LlmCallError as exc:
        raise JobError(FailureCode.PROVIDER_ERROR, CALL_MESSAGE, retryable=True) from exc
    except LlmSchemaError as exc:
        raise JobError(FailureCode.LLM_SCHEMA, SCHEMA_MESSAGE) from exc
    except ValueError as exc:
        raise JobError(FailureCode.INVALID_INPUT, str(exc)) from exc
    ctx.report_stage(JobStage.PROMPTING)
    data = result.model_dump(mode="json")
    # 후처리는 핸들러 결과만 받는다. 이름→id는 요청 때 읽은 요소를 그대로 싣는다
    data["elements"] = payload["elements"]
    return data


def _ids_by_name(elements: list[dict]) -> dict[str, int]:
    return {item["name"]: item["id"] for item in elements}


@on_success(JobType.GENERATE_SCENES)
def save_scenes(db: Session, job: Job, result: dict) -> list[FollowUp]:
    """장면을 저장하고 interviewing을 scenes_ready로 바꾼 뒤, 버전마다 이미지 작업 명세를 돌려준다.

    실행기가 이 함수 뒤에 이미지 작업 행(queued)을 만들고 succeeded와 함께 commit한다.
    여기서 commit하지 않고 작업도 넣지 않는다.
    """
    ids_by_name = _ids_by_name(result["elements"])
    scenes = [{key: value for key, value in item.items() if key != "confidence_level"} for item in result["scenes"]]
    for item in scenes:
        unknown = [name for name in item.get("element_names", []) if name not in ids_by_name]
        if unknown:
            raise JobError(FailureCode.LLM_SCHEMA, SCHEMA_MESSAGE)

    created = {scene.order: scene for scene in scene_repo.create_scenes(db, job.dream_id, scenes)}
    for item in scenes:
        scene = created[item["order"]]
        version = scene.current_version
        expected = [ids_by_name[name] for name in item.get("element_names", [])]
        stored = [] if version is None else [int(element_id) for element_id in (version.element_ids or [])]
        if version is None or stored != expected:
            raise JobError(FailureCode.LLM_SCHEMA, SCHEMA_MESSAGE)

    # 인물 외형이 틀려도 장면 생성은 계속한다. set_character_appearances는 검사에 실패하면
    # 쓰기와 flush 전에 InvalidData를 던지므로, 세션은 그대로 이어서 쓸 수 있다. savepoint는 쓰지 않는다.
    try:
        extraction_repo.set_character_appearances(db, job.dream_id, result.get("characters") or [])
    except InvalidData as exc:
        logger.warning(
            "꿈 %s 인물 외형을 저장하지 않습니다: %s names=%s",
            job.dream_id,
            exc.message,
            exc.detail.get("names"),
        )

    # 이미지 payload의 인물 외형은 이 연결을 본 뒤 읽는다. 실패해도 장면 작업은 계속되고, commit은 하지 않는다.
    world_service.link_dream_elements_to_world(db, job.dream_id)

    try:
        ensure_transition(DreamStatus.INTERVIEWING, DreamStatus.SCENES_READY)
    except InvalidState as exc:
        raise JobError(FailureCode.INVALID_INPUT, STATE_MESSAGE) from exc
    if not dream_repo.transition_status(db, job.dream_id, DreamStatus.INTERVIEWING, DreamStatus.SCENES_READY):
        raise JobError(FailureCode.INVALID_INPUT, STATE_MESSAGE)

    followups = []
    for item in scenes:
        scene = created[item["order"]]
        version = scene.current_version
        characters = None if version is None else scene_repo.list_scene_characters(db, version.id)
        if version is None or characters is None:
            logger.warning("장면 %s의 장면 버전이 없어 이미지 작업을 등록하지 않습니다.", scene.id)
            continue
        followups.append(
            FollowUp(
                job_type=JobType.GENERATE_IMAGE,
                target_id=version.id,
                payload=image_payload(db, job.dream_id, version, item["image_prompt_en"], characters),
            )
        )
        if not settings.narration_enabled:
            continue
        payload = narration_payload(version)
        if payload is None:
            logger.warning("장면 %s의 나레이션 문장이 없어 나레이션 작업을 등록하지 않습니다.", scene.id)
            continue
        followups.append(
            FollowUp(
                job_type=JobType.GENERATE_NARRATION,
                target_id=version.id,
                payload=payload,
            )
        )
    return followups
