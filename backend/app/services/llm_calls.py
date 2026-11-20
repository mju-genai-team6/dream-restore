"""요청 안에서 LLM을 부르는 처리(질문 생성, 재추출, STT)의 공통 부분: 꿈별 잠금, 오류 변환."""
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from app.core.errors import LlmFailed, SttFailed, UpstreamTimeout
from app.llm.client import LlmCallError, LlmError, LlmSchemaError, LlmTimeoutError

T = TypeVar("T")

TIMEOUT_MESSAGE = "AI 응답이 늦어지고 있습니다. 잠시 후 다시 시도해 주세요."
STT_FAILED_MESSAGE = "음성을 텍스트로 변환하지 못했습니다. 다시 녹음하거나 텍스트로 입력해 주세요."

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
    except LlmTimeoutError as exc:
        # LlmCallError의 하위라 아래보다 먼저 잡아야 504가 된다
        raise UpstreamTimeout(TIMEOUT_MESSAGE) from exc
    except LlmCallError as exc:
        raise LlmFailed(failed_message) from exc
    except LlmSchemaError as exc:
        raise LlmFailed(failed_message) from exc


def call_stt(func: Callable[..., T], *args) -> T:
    """STT 예외를 API 오류로 바꾼다. 시간 초과는 504, 그 밖은 502 STT_FAILED.

    키가 없으면 transcribe가 SttError가 아닌 LlmCallError를 던지므로 LlmError 전체를 잡는다.
    SttEmptyResultError도 빈 문자열과 같은 502 STT_FAILED, 같은 메시지다.
    LlmTimeoutError는 LlmError의 하위라 먼저 잡아야 시간 초과가 502가 되지 않는다.
    """
    try:
        return func(*args)
    except LlmTimeoutError as exc:
        raise UpstreamTimeout(TIMEOUT_MESSAGE) from exc
    except LlmError as exc:
        raise SttFailed(STT_FAILED_MESSAGE) from exc
