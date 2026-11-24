"""로그 출력 설정과 원인 예외 요약."""
import logging

from uvicorn.logging import DefaultFormatter

MESSAGE_LIMIT = 200
_LOGGER_NAMES = ("app", "worker")


def configure_logging() -> None:
    """app·worker 로거의 INFO 이상을 uvicorn과 같은 형식(로거 이름 포함)으로 출력한다.

    uvicorn은 자기 로거만 설정하고 루트 로거에는 핸들러를 달지 않는다. 설정이 없으면 WARNING 이상만
    시각·로거 이름 없이 나온다. 이미 핸들러가 있으면 다시 달지 않는다.
    """
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if logger.handlers:
            continue
        handler = logging.StreamHandler()
        handler.setFormatter(DefaultFormatter("%(levelprefix)s %(name)s: %(message)s"))
        logger.addHandler(handler)


def next_cause(exc: BaseException) -> BaseException | None:
    if exc.__cause__ is not None:
        return exc.__cause__
    return None if exc.__suppress_context__ else exc.__context__


def exception_chain(exc: BaseException) -> str:
    """예외 종류 이름 사슬. 예: "LlmSchemaError <- ValidationError"."""
    names: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__)
        current = next_cause(current)
    return " <- ".join(names)


def short_message(exc: BaseException) -> str:
    """한 줄로 펴서 앞 MESSAGE_LIMIT자까지만. 원문·응답 조각이 길게 찍히지 않게 한다."""
    text = " ".join(str(exc).split())
    return text if len(text) <= MESSAGE_LIMIT else text[:MESSAGE_LIMIT] + "…"
