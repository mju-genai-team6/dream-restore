"""요소 목록·확신도 저장. 인터뷰가 끝난 뒤 첫 요소 목록 조회 때 재추출한다."""
from sqlalchemy.orm import Session

from app.core.enums import DreamStatus, ExtractionPhase, JobType
from app.core.errors import InvalidState, ValidationFailed
from app.llm.interview import reextract
from app.llm.schemas import InterviewAnswer
from app.models.dream import Dream
from app.models.interview import DreamElement, Extraction
from app.repositories import InvalidData
from app.repositories import extractions as extraction_repo
from app.repositories import interview as interview_repo
from app.repositories import jobs as job_repo
from app.schemas.elements import ConfidenceUpdate, ElementItem, ElementListResponse
from app.services.interview import confirmed_text, require_dream
from app.services.llm_calls import call_llm, dream_lock
from app.services.transactions import commit, expire_loaded, rollback


def _is_after_interview(extraction: Extraction | None) -> bool:
    return extraction is not None and extraction.phase == ExtractionPhase.AFTER_INTERVIEW.value


def _element_response(rows: list[DreamElement]) -> ElementListResponse:
    return ElementListResponse(
        elements=[
            ElementItem(
                element_id=row.id,
                type=row.type,
                name=row.name,
                description=row.description,
                confidence=row.confidence,
            )
            for row in rows
        ]
    )


def _ensure_interview_done(db: Session, dream: Dream) -> None:
    answered, total = interview_repo.get_progress(db, dream.id)
    if DreamStatus(dream.status) != DreamStatus.INTERVIEWING or total == 0 or answered < total:
        raise InvalidState(
            "인터뷰를 마친 뒤 요소를 확인할 수 있습니다.",
            {"status": dream.status, "answered": answered, "total": total},
        )


def list_elements(db: Session, dream_id: int) -> ElementListResponse:
    dream = require_dream(db, dream_id)
    if _is_after_interview(extraction_repo.get_latest_extraction(db, dream_id)):
        return _element_response(extraction_repo.list_elements(db, dream_id))

    _ensure_interview_done(db, dream)
    text = confirmed_text(dream)
    with dream_lock(dream_id):
        if _is_after_interview(extraction_repo.get_latest_extraction(db, dream_id)):
            return _element_response(extraction_repo.list_elements(db, dream_id))
        answers = [
            InterviewAnswer(question=row.text, answer=None if row.skipped else row.answer)
            for row in interview_repo.list_questions(db, dream_id)
        ]
        result = call_llm(
            reextract, text, answers, failed_message="요소를 정리하지 못했습니다. 다시 시도해 주세요."
        )
        # extractions에는 유니크 제약이 없어 중복 재추출은 이 잠금으로만 막는다(서버 프로세스 하나 기준).
        # 다른 프로세스와 겹쳐 두 번 저장돼도 요소 목록은 가장 최근 추출만 보여 준다
        try:
            extraction_repo.save_extraction(
                db, dream_id, ExtractionPhase.AFTER_INTERVIEW, result.model_dump(mode="json"), len(text)
            )
            commit(db)
        except Exception:
            rollback(db)
            raise
    return _element_response(extraction_repo.list_elements(db, dream_id))


def set_confidences(db: Session, dream_id: int, body: ConfidenceUpdate) -> ElementListResponse:
    """요청에 담긴 요소만 저장한다(일부 저장 허용). 빈 확신도 검사는 장면 생성 요청에서 한다.

    장면 생성 요청과 같은 꿈별 잠금 안에서 검사·저장해, 작업 등록과 엇갈려 저장되지 않게 한다.
    """
    with dream_lock(dream_id):
        expire_loaded(db)
        return _set_confidences(db, dream_id, body)


def _set_confidences(db: Session, dream_id: int, body: ConfidenceUpdate) -> ElementListResponse:
    dream = require_dream(db, dream_id)
    if DreamStatus(dream.status) != DreamStatus.INTERVIEWING:
        raise InvalidState("현재 단계에서는 확신도를 저장할 수 없습니다.", {"status": dream.status})
    if not _is_after_interview(extraction_repo.get_latest_extraction(db, dream_id)):
        raise InvalidState("요소 목록을 먼저 확인해 주세요.", {"status": dream.status})
    # failed 작업은 막지 않는다. 확신도를 고친 뒤 다시 요청할 수 있다
    # TODO(C-S3-01): 가짜 작업 성공 후에도 막히는지 확인 (scenes_ready로 바뀌면 위 상태 검사로 막힘)
    scenes_job = next(
        (job for job in job_repo.get_active_jobs(db, dream_id) if job.type == JobType.GENERATE_SCENES),
        None,
    )
    if scenes_job is not None:
        raise InvalidState(
            "장면을 만드는 중에는 확신도를 바꿀 수 없습니다.",
            {"status": dream.status, "job_id": scenes_job.id},
        )

    requested = [item.element_id for item in body.items]
    duplicated = sorted({element_id for element_id in requested if requested.count(element_id) > 1})
    if duplicated:
        raise ValidationFailed("같은 요소가 여러 번 들어 있습니다.", {"element_ids": duplicated})
    current_ids = {row.id for row in extraction_repo.list_elements(db, dream_id)}
    unknown = sorted(set(requested) - current_ids)
    if unknown:
        raise ValidationFailed("요소 목록에 없는 요소입니다.", {"element_ids": unknown})

    try:
        extraction_repo.set_confidences(
            db, dream_id, {item.element_id: item.confidence.value for item in body.items}
        )
        commit(db)
    except InvalidData as exc:
        rollback(db)
        raise ValidationFailed(exc.message, exc.detail) from exc
    except Exception:
        rollback(db)
        raise
    # set_confidences는 저장한 요소만 돌려주므로 전체 목록을 다시 읽는다
    return _element_response(extraction_repo.list_elements(db, dream_id))
