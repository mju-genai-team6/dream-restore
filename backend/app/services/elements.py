"""요소 목록·확신도 저장. 인터뷰가 끝난 뒤 첫 요소 목록 조회 때 재추출한다."""
from sqlalchemy.orm import Session

from app.core.enums import DreamStatus, ExtractionPhase
from app.core.errors import InvalidState, ValidationFailed
from app.llm.interview import reextract
from app.llm.schemas import InterviewAnswer
from app.models.dream import Dream
from app.models.interview import DreamElement, Extraction
from app.schemas.elements import ConfidenceUpdate, ElementItem, ElementListResponse
from app.services.interview import confirmed_text, require_dream
from app.services.llm_calls import call_llm, dream_lock
from app.services.stubs import elements as element_repo
from app.services.stubs import interview as interview_repo
from app.services.transactions import commit, rollback


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


def _ensure_interview_done(db: Session | None, dream: Dream) -> None:
    answered, total = interview_repo.get_progress(db, dream.id)
    if DreamStatus(dream.status) != DreamStatus.INTERVIEWING or total == 0 or answered < total:
        raise InvalidState(
            "인터뷰를 마친 뒤 요소를 확인할 수 있습니다.",
            {"status": dream.status, "answered": answered, "total": total},
        )


def list_elements(db: Session | None, dream_id: int) -> ElementListResponse:
    dream = require_dream(db, dream_id)
    if _is_after_interview(element_repo.get_latest_extraction(db, dream_id)):
        return _element_response(element_repo.list_elements(db, dream_id))

    _ensure_interview_done(db, dream)
    text = confirmed_text(dream)
    with dream_lock(dream_id):
        if _is_after_interview(element_repo.get_latest_extraction(db, dream_id)):
            return _element_response(element_repo.list_elements(db, dream_id))
        answers = [
            InterviewAnswer(question=row.text, answer=None if row.skipped else row.answer)
            for row in interview_repo.list_questions(db, dream_id)
        ]
        result = call_llm(
            reextract, text, answers, failed_message="요소를 정리하지 못했습니다. 다시 시도해 주세요."
        )
        # TODO(C-S2-06): 실제 DB에서 중복 저장 충돌이 나면 rollback 후 저장된 최신 추출의 요소를 다시 읽어 돌려준다
        try:
            element_repo.save_extraction(
                db,
                dream_id=dream_id,
                phase=ExtractionPhase.AFTER_INTERVIEW.value,
                payload=result.model_dump(mode="json"),
                elements=[element.model_dump(mode="json") for element in result.elements],
                text_length=len(text),
            )
            commit(db)
        except Exception:
            rollback(db)
            raise
    return _element_response(element_repo.list_elements(db, dream_id))


def set_confidences(db: Session | None, dream_id: int, body: ConfidenceUpdate) -> ElementListResponse:
    """요청에 담긴 요소만 저장한다(일부 저장 허용). 빈 확신도 검사는 장면 생성 요청에서 한다."""
    dream = require_dream(db, dream_id)
    if DreamStatus(dream.status) != DreamStatus.INTERVIEWING:
        raise InvalidState("현재 단계에서는 확신도를 저장할 수 없습니다.", {"status": dream.status})
    if not _is_after_interview(element_repo.get_latest_extraction(db, dream_id)):
        raise InvalidState("요소 목록을 먼저 확인해 주세요.", {"status": dream.status})
    # TODO(C-S2-04): 이 꿈에 generate_scenes 작업이 있으면 409 INVALID_STATE

    requested = [item.element_id for item in body.items]
    duplicated = sorted({element_id for element_id in requested if requested.count(element_id) > 1})
    if duplicated:
        raise ValidationFailed("같은 요소가 여러 번 들어 있습니다.", {"element_ids": duplicated})
    current_ids = {row.id for row in element_repo.list_elements(db, dream_id)}
    unknown = sorted(set(requested) - current_ids)
    if unknown:
        raise ValidationFailed("요소 목록에 없는 요소입니다.", {"element_ids": unknown})

    try:
        rows = element_repo.set_confidences(
            db, dream_id, {item.element_id: item.confidence.value for item in body.items}
        )
        commit(db)
    except Exception:
        rollback(db)
        raise
    return _element_response(rows)
