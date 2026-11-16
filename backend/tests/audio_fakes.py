"""음성 업로드 테스트용 파일 내용과 가짜 transcribe. app.services.dreams.transcribe 자리에 끼운다."""
import threading
import time
from pathlib import Path

import httpx
import openai

from app.llm.client import LlmCallError, SttError

WEBM_BYTES = b"\x1a\x45\xdf\xa3fake-webm"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42fake-mp4"
TRANSCRIPT = "하늘을 나는 꿈을 꿨어요."


class FakeTranscribe:
    """받은 경로를 기록하고 정해진 결과를 돌려준다. mode: ok, stt_error, timeout, no_key."""

    def __init__(self, text: str = TRANSCRIPT, *, mode: str = "ok", delay: float = 0.0, on_call=None):
        self.text = text
        self.mode = mode
        self.delay = delay
        self.on_call = on_call
        self.paths: list[str] = []
        self.running = 0
        self.max_running = 0
        self._guard = threading.Lock()

    def __call__(self, audio_path: str | Path) -> str:
        with self._guard:
            self.paths.append(str(audio_path))
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            if self.on_call:
                self.on_call(audio_path)
            if self.delay:
                time.sleep(self.delay)
            if self.mode == "stt_error":
                raise SttError("음성 인식 실패: 테스트")
            if self.mode == "timeout":
                request = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
                try:
                    raise openai.APITimeoutError(request=request)
                except openai.APITimeoutError as exc:
                    raise SttError(f"음성 인식 실패: {exc}") from exc
            if self.mode == "no_key":
                raise LlmCallError("OPENAI_API_KEY가 설정되지 않았습니다.")
            return self.text
        finally:
            with self._guard:
                self.running -= 1
