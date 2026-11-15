"""공통 응답 스키마: 오류 응답 형식 (docs/rules/error-format.md)."""
from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(description="프론트엔드가 분기에 쓰는 오류 코드")
    message: str = Field(description="화면에 그대로 보여 줄 수 있는 한국어 문장")
    detail: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


_ERROR_EXAMPLES: dict[int, tuple[str, str, str, dict[str, Any]]] = {
    400: ("요청 값 형식 오류", "VALIDATION_ERROR", "요청 값을 확인해 주세요.", {"errors": []}),
    404: ("대상 없음", "NOT_FOUND", "꿈 기록을 찾을 수 없습니다.", {"dream_id": 999}),
    409: (
        "현재 상태에서 허용되지 않은 요청",
        "INVALID_STATE",
        "현재 단계에서는 할 수 없는 요청입니다.",
        {"status": "interviewing"},
    ),
    413: ("음성 파일 25MB 초과", "AUDIO_TOO_LARGE", "음성 파일은 25MB까지 올릴 수 있습니다.", {}),
    415: (
        "허용하지 않은 음성 형식",
        "UNSUPPORTED_AUDIO",
        "webm, mp4, m4a 형식의 음성 파일만 올릴 수 있습니다.",
        {},
    ),
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """라우터 `responses=`에 넣을 오류 응답 문서를 만든다."""
    result: dict[int | str, dict[str, Any]] = {}
    for status_code in status_codes:
        description, code, message, detail = _ERROR_EXAMPLES[status_code]
        result[status_code] = {
            "model": ErrorResponse,
            "description": description,
            "content": {
                "application/json": {
                    "example": {"error": {"code": code, "message": message, "detail": detail}}
                }
            },
        }
    return result
