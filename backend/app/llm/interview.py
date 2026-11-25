"""인터뷰 모듈: STT, 요소 추출 + 되묻기 질문, 인터뷰 후 재추출."""
import logging
import re
from pathlib import Path

from app.core.config import settings
from app.llm.client import (
    Complete,
    LlmTimeoutError,
    SttEmptyResultError,
    SttError,
    call_json,
    get_openai_client,
    load_prompt,
)
from app.llm.schemas import ExtractionResult, InterviewAnswer, ReextractionResult

NO_MEMORY = "(기억나지 않음)"

logger = logging.getLogger(__name__)

# Whisper는 말소리가 없는 녹음(무음, 잡음)에서 학습 데이터에 흔한 문장을 지어낸다.
# 실제 확인: 무음 6초 → "고맙습니다.", 작은 잡음 6초 → "시청해주셔서 감사합니다." (둘 다 no_speech_prob 0.88~0.94,
# 실제 말소리는 0.0). 구간(segment)마다 아래 둘 중 하나면 버린다.
# 1) no_speech_prob가 이 값 이상 (Whisper 자체 기준값 0.6과 같음)
NO_SPEECH_THRESHOLD = 0.6
# 2) 구간 전체가 방송·영상 자막에서 온 알려진 문장 (no_speech_prob가 낮게 나와도 버림)
_HALLUCINATION_PATTERNS = [
    r"(MBC|KBS|SBS|JTBC|YTN)\s*뉴스\s*[^.!?]{0,15}입니다",  # 예: "MBC 뉴스 이덕영입니다", "... 기자입니다"
    r"시청해\s*주셔서\s*(정말\s*)?감사(합니다|드립니다)",
    r"구독(과|하고)?\s*좋아요.*",
    r"(한글\s*)?자막\s*(제공|by|제작).*",
    r"다음\s*(영상|시간)에서\s*(만나요|뵙겠습니다)",
]
_HALLUCINATION_RE = re.compile(r"^\s*(?:" + "|".join(_HALLUCINATION_PATTERNS) + r")[\s.!~]*$", re.IGNORECASE)


def is_hallucination(text: str) -> bool:
    """구간 문장 전체가 알려진 Whisper 환각 문장인지."""
    return bool(_HALLUCINATION_RE.match(text))


def _speech_text(result) -> str:
    """verbose_json 결과에서 말소리가 없는 구간과 환각 문장을 빼고 이어 붙인다."""
    segments = getattr(result, "segments", None)
    if not segments:
        # 구간 정보가 없으면 전체 문장으로만 판단
        text = (getattr(result, "text", "") or "").strip()
        return "" if is_hallucination(text) else text
    kept: list[str] = []
    for seg in segments:
        text = (seg.text or "").strip()
        no_speech = getattr(seg, "no_speech_prob", 0.0) or 0.0
        if not text:
            continue
        if no_speech >= NO_SPEECH_THRESHOLD or is_hallucination(text):
            logger.warning("STT 구간을 버림 (말소리 없음 또는 환각): no_speech_prob=%.2f text=%r", no_speech, text)
            continue
        kept.append(text)
    return " ".join(kept)


def transcribe(audio_path: str | Path) -> str:
    """녹음 파일을 텍스트로 바꿉니다 (Whisper).

    무음·잡음에서 Whisper가 지어낸 문장("고맙습니다.", "MBC 뉴스 ...입니다")은 버립니다.
    남는 말이 없으면 SttEmptyResultError를 던집니다.
    """
    import openai

    path = Path(audio_path)
    if not path.is_file():
        raise SttError(f"음성 파일을 찾을 수 없습니다: {path}")
    client = get_openai_client()
    try:
        with path.open("rb") as f:
            result = client.audio.transcriptions.create(
                model=settings.stt_model, file=f, language="ko", response_format="verbose_json"
            )
    except openai.APITimeoutError as e:
        raise LlmTimeoutError(f"음성 인식 시간 초과: {e}") from e
    except openai.OpenAIError as e:
        raise SttError(f"음성 인식 실패: {e}") from e
    text = _speech_text(result)
    if not text:
        raise SttEmptyResultError("음성에서 인식된 내용이 없습니다.")
    return text


def extract_and_ask(text: str, complete: Complete | None = None) -> ExtractionResult:
    """꿈 원문에서 요소를 뽑고 되묻기 질문 5~7개를 만듭니다 (LLM 1회 호출)."""
    user = f"## 꿈 내용\n{_require_text(text)}"
    return call_json(load_prompt("extract_and_ask"), user, ExtractionResult, complete)


def reextract(
    text: str, answers: list[InterviewAnswer], complete: Complete | None = None
) -> ReextractionResult:
    """원문과 인터뷰 답변을 합쳐 요소를 다시 뽑습니다."""
    lines = [f"## 꿈 내용\n{_require_text(text)}", "", "## 되묻기 질문과 답변"]
    for i, a in enumerate(answers, start=1):
        answer = (a.answer or "").strip() or NO_MEMORY
        lines.append(f"{i}. 질문: {a.question}\n   답변: {answer}")
    return call_json(load_prompt("reextract"), "\n".join(lines), ReextractionResult, complete)


def _require_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("꿈 내용이 비어 있습니다.")
    return text
