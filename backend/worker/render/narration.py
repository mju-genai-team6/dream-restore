"""generate_narration 작업 함수 (E2, 선택 기능 — 계획서 3.4).

장면 설명 문장을 TTS로 읽어 장면 버전 폴더에 narration.mp3로 저장한다.
E1 렌더링은 이 파일이 있으면 음성 길이에 맞춰 장면 길이를 늘린다.

payload (Job API가 넣어 줌):
    scene_id: int        장면 id
    version_no: int      장면 버전 번호 (이미지와 같은 버전 폴더에 저장)
    text: str            읽을 문장. D의 summary_ko 또는 짧게 다듬은 나레이션 문장
    voice: str           (선택) 기본값은 설정의 tts_voice

저장 위치: media(storage)/dreams/{dreamId}/scenes/{sceneId}/v{versionNo}/narration.mp3  (paths.scene_narration)
가짜 모드: .env에 TTS_FAKE=true면 API를 부르지 않고 글자 수에 맞춘 무음 mp3를 저장한다 (비용 없이 흐름 확인용).
    API 키도 필요 없다. 건너뛰고 싶으면 작업을 만들지 않으면 된다 (E1은 narration.mp3가 없으면 나레이션 없이 렌더링).

결과 (나레이션 기록):
    narration_path, duration_seconds, text, model, voice, speed, attempts, generated_at
"""
from __future__ import annotations

import math
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime

import openai
from mutagen import MutagenError
from mutagen.mp3 import MP3
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import settings
from app.core.enums import FailureCode, JobStage, JobType
from app.jobs.context import JobContext, JobError
from app.jobs.registry import register
from app.storage import paths


class NarrationSettings(BaseSettings):
    """나레이션 설정. 공용 config와 같은 .env에서 TTS 관련 값만 읽는다."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "sage"  # 차분한 음성. 비교 실험 후 확정
    tts_speed: float = 0.95  # 꿈 분위기에 맞게 조금 느리게
    tts_instructions: str = "Speak softly and calmly in Korean, like recalling a dream."
    tts_max_chars: int = 200  # 너무 길면 장면이 지나치게 길어지므로 제한
    tts_max_retries: int = 2
    tts_fake: bool = False  # True면 무음 mp3를 만든다 (API 호출·비용 없음)


tts_settings = NarrationSettings()

# 재시도 사이 대기 (테스트에서 바꿔 끼운다)
sleep: Callable[[float], None] = time.sleep


def get_client() -> openai.OpenAI:
    """테스트에서는 가짜 클라이언트로 바꿔 끼운다. TTS 전용 키가 없으면 OpenAI 키를 쓴다."""
    api_key = settings.tts_api_key or settings.openai_api_key
    if not api_key:
        raise JobError(FailureCode.PROVIDER_ERROR, "TTS_API_KEY 또는 OPENAI_API_KEY가 설정되지 않았습니다.")
    return openai.OpenAI(api_key=api_key, timeout=settings.job_timeout_seconds, max_retries=0)


def _parse_payload(payload: dict) -> tuple[int, int, str, str]:
    try:
        scene_id = int(payload["scene_id"])
        version_no = int(payload["version_no"])
        text = " ".join(str(payload["text"]).split())
    except (KeyError, TypeError, ValueError) as e:
        raise JobError(FailureCode.INVALID_INPUT, f"payload 값이 올바르지 않습니다: {e}") from e
    if version_no < 1 or not text:
        raise JobError(FailureCode.INVALID_INPUT, "version_no는 1 이상, text는 비어 있으면 안 됩니다.")
    if len(text) > tts_settings.tts_max_chars:
        raise JobError(
            FailureCode.INVALID_INPUT,
            f"나레이션 문장이 너무 깁니다: {len(text)}자 (최대 {tts_settings.tts_max_chars}자)",
        )
    voice = str(payload.get("voice") or tts_settings.tts_voice)
    return scene_id, version_no, text, voice


# 가짜 모드용 무음 프레임: MPEG-1 Layer III, 128kbps, 44.1kHz. 프레임 1개 = 1152샘플 ≈ 0.02612초
_SILENT_FRAME = bytes([0xFF, 0xFB, 0x90, 0x64]) + bytes(417 - 4)
_FAKE_SECONDS_PER_CHAR = 0.15  # 한국어 낭독 속도 추정
_FRAME_SECONDS = 1152 / 44100


def fake_speech(text: str) -> bytes:
    """글자 수에 비례한 길이(최소 1초)의 무음 mp3 바이트."""
    seconds = max(1.0, len(text) * _FAKE_SECONDS_PER_CHAR)
    return _SILENT_FRAME * math.ceil(seconds / _FRAME_SECONDS)


def _request_speech(client: openai.OpenAI, text: str, voice: str) -> bytes:
    """TTS를 한 번 호출하고 mp3 바이트를 돌려준다. 오류는 팀 공통 실패 사유로 바꾼다."""
    try:
        resp = client.audio.speech.create(
            model=tts_settings.tts_model,
            voice=voice,
            input=text,
            instructions=tts_settings.tts_instructions,
            response_format="mp3",
            speed=tts_settings.tts_speed,
        )
    except openai.APITimeoutError as e:
        raise JobError(FailureCode.TIMEOUT, "나레이션 생성 시간이 초과되었습니다.", retryable=True) from e
    except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as e:
        raise JobError(FailureCode.PROVIDER_ERROR, f"TTS 서비스 오류: {e}", retryable=True) from e
    except openai.APIError as e:
        raise JobError(FailureCode.PROVIDER_ERROR, f"TTS 요청 오류: {e}") from e

    audio = resp.content
    if not audio:
        raise JobError(FailureCode.PROVIDER_ERROR, "응답에 음성 데이터가 없습니다.", retryable=True)
    return audio


def _generate_with_retry(ctx: JobContext, client: openai.OpenAI, text: str, voice: str) -> tuple[bytes, int]:
    max_attempts = 1 + max(tts_settings.tts_max_retries, 0)
    for attempt in range(1, max_attempts + 1):
        try:
            return _request_speech(client, text, voice), attempt
        except JobError as e:
            if not e.retryable or attempt == max_attempts:
                e.message = f"{e.message} (시도 {attempt}회)"
                raise
            wait = 2 ** (attempt - 1)
            ctx.logger.warning("나레이션 생성 실패 %s, %s초 뒤 재시도 (%s/%s)", e.code, wait, attempt, max_attempts)
            sleep(wait)
    raise AssertionError("unreachable")


def mp3_duration(path) -> float:
    """mp3 재생 길이(초). 파일이 mp3가 아니면 실패 처리한다."""
    try:
        return round(MP3(path).info.length, 2)
    except MutagenError as e:
        raise JobError(FailureCode.PROVIDER_ERROR, "받은 음성 파일을 읽을 수 없습니다.") from e


@register(JobType.GENERATE_NARRATION)
def handle_generate_narration(ctx: JobContext, payload: dict) -> dict:
    scene_id, version_no, text, voice = _parse_payload(payload)

    target = ctx.path_for("scene_narration", scene_id=scene_id, version_no=version_no)
    if target.exists():
        raise JobError(FailureCode.INVALID_INPUT, f"이미 나레이션이 있는 장면 버전입니다: v{version_no}")

    ctx.report_stage(JobStage.REQUESTING)
    ctx.logger.info("나레이션 생성 요청 scene=%s v%s voice=%s", scene_id, version_no, voice)
    if tts_settings.tts_fake:
        ctx.logger.info("TTS_FAKE: 무음 mp3를 만듭니다 scene=%s v%s", scene_id, version_no)
        audio, attempts = fake_speech(text), 0
    else:
        audio, attempts = _generate_with_retry(ctx, get_client(), text, voice)

    ctx.report_stage(JobStage.SAVING)
    tmp_file = ctx.tmp_dir() / f"scene_{scene_id}_v{version_no}_narration.mp3"
    tmp_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file.write_bytes(audio)
    duration = mp3_duration(tmp_file)  # 옮기기 전에 검증
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(tmp_file, target)

    return {
        "narration_path": str(paths.scene_narration(ctx.dream_id, scene_id, version_no)),
        "duration_seconds": duration,
        "text": text,
        "model": tts_settings.tts_model,
        "voice": voice,
        "fake": tts_settings.tts_fake,
        "speed": tts_settings.tts_speed,
        "attempts": attempts,
        "generated_at": datetime.now(UTC).isoformat(),
    }
