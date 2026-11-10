"""인터뷰 모듈: STT, 요소 추출 + 되묻기 질문, 인터뷰 후 재추출."""
from pathlib import Path

from app.core.config import settings
from app.llm.client import Complete, SttError, call_json, get_openai_client, load_prompt
from app.llm.schemas import ExtractionResult, InterviewAnswer, ReextractionResult

NO_MEMORY = "(기억나지 않음)"


def transcribe(audio_path: str | Path) -> str:
    """녹음 파일을 텍스트로 바꿉니다 (Whisper)."""
    import openai

    path = Path(audio_path)
    if not path.is_file():
        raise SttError(f"음성 파일을 찾을 수 없습니다: {path}")
    client = get_openai_client()
    try:
        with path.open("rb") as f:
            result = client.audio.transcriptions.create(model=settings.stt_model, file=f, language="ko")
    except openai.OpenAIError as e:
        raise SttError(f"음성 인식 실패: {e}") from e
    text = (result.text or "").strip()
    if not text:
        raise SttError("음성에서 인식된 내용이 없습니다.")
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
