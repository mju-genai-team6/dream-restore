"""질문 조회·답변 저장 스키마."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.services import mock_data


class InterviewQuestionItem(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": mock_data.QUESTION_ITEM_EXAMPLES})

    question_id: int
    order: int
    target_element: str | None = None
    question: str
    answered: bool
    skipped: bool
    answer: str | None = Field(description="답변 내용. 답하지 않았거나 건너뛰면 null.")


class InterviewResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.INTERVIEW]})

    questions: list[InterviewQuestionItem]
    answered: int
    total: int


class AnswerCreate(BaseModel):
    """답변하거나(answer) 건너뛴다(skipped=true)."""

    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.ANSWER_CREATE]})

    question_id: int
    answer: str | None = Field(default=None, min_length=1, max_length=1000)
    skipped: bool = False

    @model_validator(mode="after")
    def _answer_or_skipped(self) -> "AnswerCreate":
        if not self.skipped and not self.answer:
            raise PydanticCustomError(
                "answer_required", "답변을 입력하거나 건너뛰기를 선택해 주세요."
            )
        return self


class AnswerResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [mock_data.ANSWER_SAVED]})

    remaining: int
    completed: bool
