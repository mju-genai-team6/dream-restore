"""질문 조회·답변 저장. 지금은 목업(mock_data)을 돌려준다."""
from app.schemas.interview import AnswerCreate, AnswerResponse, InterviewResponse
from app.services import mock_data
from app.services.dreams import ensure_sample_dream


# TODO(C-S2-02): 첫 호출 시 extract_and_ask → save_questions, 이후 list_questions
def get_interview(dream_id: int) -> InterviewResponse:
    ensure_sample_dream(dream_id)
    return InterviewResponse.model_validate(mock_data.INTERVIEW)


# TODO(C-S2-02): save_answer, get_progress, 완료 시 reextract(C-S2-03)
def save_answer(dream_id: int, _: AnswerCreate) -> AnswerResponse:
    ensure_sample_dream(dream_id)
    return AnswerResponse.model_validate(mock_data.ANSWER_SAVED)
