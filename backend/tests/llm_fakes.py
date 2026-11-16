"""API 테스트용 가짜 LLM. app.llm.client.openai_complete 자리에 끼워 실제 검증 흐름을 그대로 탄다."""
import threading
import time
from pathlib import Path

import httpx
import openai

from app.llm.client import LlmCallError, load_prompt

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "examples"
EXTRACTION_JSON = (EXAMPLES / "interview.json").read_text(encoding="utf-8")
ELEMENTS_JSON = (EXAMPLES / "elements.json").read_text(encoding="utf-8")


class FakeLlm:
    """프롬프트 종류(질문 생성 / 재추출)에 맞는 예시 JSON을 돌려주고 호출을 기록한다."""

    def __init__(self, *, delay: float = 0.0, mode: str = "ok"):
        self.delay = delay
        self.mode = mode
        self.calls: list[tuple[str, list[dict]]] = []
        self._guard = threading.Lock()
        self._reextract_prompt = load_prompt("reextract")

    def kind_count(self, kind: str) -> int:
        return sum(1 for called_kind, _ in self.calls if called_kind == kind)

    def __call__(self, messages: list[dict]) -> str:
        kind = "reextract" if messages[0]["content"] == self._reextract_prompt else "extract_and_ask"
        with self._guard:
            self.calls.append((kind, [dict(m) for m in messages]))
        if self.delay:
            time.sleep(self.delay)
        if self.mode == "timeout":
            request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            try:
                raise openai.APITimeoutError(request=request)
            except openai.APITimeoutError as exc:
                raise LlmCallError(f"LLM 호출 실패: {exc}") from exc
        if self.mode == "bad_format":
            return "{}"
        return ELEMENTS_JSON if kind == "reextract" else EXTRACTION_JSON
