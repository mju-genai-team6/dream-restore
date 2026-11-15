"""요청 안에서 LLM을 부르는 처리(질문 생성, 재추출)의 공통 부분: 꿈별 잠금, 오류 변환."""
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

import openai

from app.core.errors import LlmFailed, UpstreamTimeout
from app.llm.client import LlmCallError, LlmSchemaError

T = TypeVar("T")

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def dream_lock(dream_id: int) -> Iterator[None]:
    """같은 꿈의 LLM 호출·저장을 한 번에 하나만 실행한다. 서버 프로세스 하나 안에서만 유효하다."""
    with _locks_guard:
        lock = _locks.setdefault(dream_id, threading.Lock())
    with lock:
        yield


def call_llm(func: Callable[..., T], *args, failed_message: str) -> T:
    """LLM 예외를 API 오류로 바꾼다. 시간 초과는 504, 그 밖의 호출 실패와 형식 오류는 502."""
    try:
        return func(*args)
    except LlmCallError as exc:
        # TODO(D): LlmTimeoutError가 추가되면 __cause__ 대신 그 예외로 판별
        if isinstance(exc.__cause__, openai.APITimeoutError):
            raise UpstreamTimeout("AI 응답이 늦어지고 있습니다. 잠시 후 다시 시도해 주세요.") from exc
        raise LlmFailed(failed_message) from exc
    except LlmSchemaError as exc:
        raise LlmFailed(failed_message) from exc
