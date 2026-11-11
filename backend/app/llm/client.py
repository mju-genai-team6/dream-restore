"""LLM 호출 공통 부분: 프롬프트 파일 읽기, JSON 응답 검증, 형식 오류 시 재요청.

형식 오류는 최대 2회 다시 요청하고, 그래도 실패하면 LlmSchemaError를 던집니다.
서버(C)는 LlmError를 잡아 LLM_FAILED / STT_FAILED 응답으로 바꿉니다.
"""
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings

PROMPT_DIR = Path(__file__).parent / "prompts"
MAX_RETRIES = 2  # 처음 1회 + 재요청 2회 = 최대 3회 호출

Message = dict[str, str]
# 대화 목록을 받아 LLM의 답(문자열)을 돌려주는 함수. 테스트에서는 가짜 함수로 바꿔 끼웁니다.
Complete = Callable[[list[Message]], str]
T = TypeVar("T", bound=BaseModel)


class LlmError(Exception):
    """app/llm 에서 나는 오류의 공통 부모."""


class LlmCallError(LlmError):
    """외부 AI 호출 자체가 실패함 (키 없음, 네트워크, 제공사 오류)."""


class LlmSchemaError(LlmError):
    """재요청까지 했는데도 LLM 출력이 스키마와 맞지 않음."""


class SttError(LlmError):
    """음성 인식 실패."""


def load_prompt(name: str) -> str:
    """prompts/<name>.md 파일 내용을 읽습니다."""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def get_openai_client():
    if not settings.openai_api_key:
        raise LlmCallError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해 주세요.")
    from openai import OpenAI  # 키 없이도 테스트를 돌릴 수 있게 여기서 import

    return OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds)


def openai_complete(messages: list[Message]) -> str:
    """실제 OpenAI 호출. JSON으로만 답하도록 요청합니다."""
    import openai

    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            response_format={"type": "json_object"},
        )
    except openai.OpenAIError as e:
        raise LlmCallError(f"LLM 호출 실패: {e}") from e
    return response.choices[0].message.content or ""


def call_json(system: str, user: str, schema: type[T], complete: Complete | None = None) -> T:
    """LLM을 호출하고 결과를 schema로 검증해 돌려줍니다.

    형식이 틀리면 무엇이 틀렸는지 알려 주며 최대 MAX_RETRIES번 다시 요청합니다.
    """
    complete = complete or openai_complete
    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error: ValidationError | None = None
    for _ in range(1 + MAX_RETRIES):
        raw = complete(messages)
        try:
            return schema.model_validate_json(raw)
        except ValidationError as e:
            last_error = e
            messages += [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": "출력이 정해진 형식과 맞지 않습니다. 아래 오류를 고쳐 JSON만 다시 출력해 주세요.\n"
                    + str(e),
                },
            ]
    raise LlmSchemaError(f"LLM 출력이 {schema.__name__} 형식과 맞지 않습니다: {last_error}")
