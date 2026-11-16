import pytest

from app.repositories import InvalidData, dreams, extractions, interview
from tests.repositories.helpers import ELEMENTS_PAYLOAD

QUESTIONS = [
    {"order": 2, "target_element": "우산", "question": "우산은 어떤 색이었나요?"},
    {"order": 1, "target_element": None, "question": "꿈 전체 분위기는 어땠나요?"},
    {"order": 3, "target_element": "할머니", "question": "할머니는 무엇을 입고 있었나요?"},
]


@pytest.fixture
def dream(db):
    return dreams.create_dream(db, input_type="text", raw_text="원문")


def test_save_and_list_questions_in_order(db, dream):
    saved = interview.save_questions(db, dream.id, QUESTIONS)
    assert [q.order for q in saved] == [1, 2, 3]
    listed = interview.list_questions(db, dream.id)
    assert [(q.order, q.text, q.target_element) for q in listed] == [
        (1, "꿈 전체 분위기는 어땠나요?", None),
        (2, "우산은 어떤 색이었나요?", "우산"),
        (3, "할머니는 무엇을 입고 있었나요?", "할머니"),
    ]


def test_answer_skip_and_progress(db, dream):
    q1, q2, _ = interview.save_questions(db, dream.id, QUESTIONS)
    assert interview.get_progress(db, dream.id) == (0, 3)

    assert interview.save_answer(db, dream.id, q1.id, answer="무서웠어요").answer == "무서웠어요"
    skipped = interview.save_answer(db, dream.id, q2.id, skipped=True)
    assert skipped.skipped is True and skipped.answer is None

    answered, total = interview.get_progress(db, dream.id)
    assert (answered, total) == (2, 3)


def test_save_answer_rejects_other_dreams_question(db, dream):
    other = dreams.create_dream(db, input_type="text", raw_text="다른 꿈")
    q = interview.save_questions(db, other.id, QUESTIONS)[0]
    assert interview.save_answer(db, dream.id, q.id, answer="x") is None
    assert interview.save_answer(db, dream.id, 999_999_999, answer="x") is None


def test_progress_without_questions(db, dream):
    assert interview.get_progress(db, dream.id) == (0, 0)


def test_save_extraction_creates_elements_without_confidence(db, dream):
    ext = extractions.save_extraction(db, dream.id, "raw", ELEMENTS_PAYLOAD, text_length=42)
    assert ext.element_count == 4 and ext.text_length == 42 and ext.payload == ELEMENTS_PAYLOAD
    elements = extractions.list_elements(db, dream.id)
    assert [e.name for e in elements] == ["학교 복도", "할머니", "우산", "두려움"]
    assert all(e.confidence is None for e in elements)
    assert all(e.extraction_id == ext.id for e in elements)


def test_list_elements_uses_latest_extraction(db, dream):
    extractions.save_extraction(db, dream.id, "raw", ELEMENTS_PAYLOAD, text_length=10)
    after = {"elements": [{"type": "person", "name": "엄마", "description": ""}]}
    extractions.save_extraction(db, dream.id, "after_interview", after, text_length=20)

    assert [e.name for e in extractions.list_elements(db, dream.id)] == ["엄마"]
    assert len(extractions.list_elements(db, dream.id, phase="raw")) == 4


def test_set_confidences(db, dream):
    extractions.save_extraction(db, dream.id, "raw", ELEMENTS_PAYLOAD, text_length=10)
    e1, e2, *_ = extractions.list_elements(db, dream.id)
    saved = extractions.set_confidences(db, dream.id, {e1.id: "high", e2.id: "low"})
    assert [(e.id, e.confidence) for e in saved] == [(e1.id, "high"), (e2.id, "low")]


@pytest.mark.parametrize("case", ["bad_value", "other_dream_element"])
def test_set_confidences_all_or_nothing(db, dream, case):
    """완료 기준: 확신도 일괄 저장은 하나라도 틀리면 전체 취소."""
    extractions.save_extraction(db, dream.id, "raw", ELEMENTS_PAYLOAD, text_length=10)
    e1, e2, *_ = extractions.list_elements(db, dream.id)

    other = dreams.create_dream(db, input_type="text", raw_text="다른 꿈")
    extractions.save_extraction(db, other.id, "raw", ELEMENTS_PAYLOAD, text_length=10)
    foreign = extractions.list_elements(db, other.id)[0]

    bad = {e1.id: "high", e2.id: "sure"} if case == "bad_value" else {e1.id: "high", foreign.id: "low"}
    with pytest.raises(InvalidData):
        extractions.set_confidences(db, dream.id, bad)
    db.expire_all()
    assert all(e.confidence is None for e in extractions.list_elements(db, dream.id))
