"""API 오류 응답 형식: {"error": {"code", "message", "detail"}}"""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class ValidationFailed(AppError):
    """요청 형식은 맞지만 저장된 데이터와 맞지 않는 값 (예: 목록에 없는 id)."""

    status_code, code = 400, "VALIDATION_ERROR"


class NotFound(AppError):
    status_code, code = 404, "NOT_FOUND"


class InvalidState(AppError):
    status_code, code = 409, "INVALID_STATE"


class VersionConflict(AppError):
    status_code, code = 409, "VERSION_CONFLICT"


class AudioTooLarge(AppError):
    status_code, code = 413, "AUDIO_TOO_LARGE"


class UnsupportedAudio(AppError):
    status_code, code = 415, "UNSUPPORTED_AUDIO"


class SttFailed(AppError):
    status_code, code = 502, "STT_FAILED"


class LlmFailed(AppError):
    status_code, code = 502, "LLM_FAILED"


class UpstreamTimeout(AppError):
    status_code, code = 504, "UPSTREAM_TIMEOUT"


def error_body(code: str, message: str, detail: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "detail": detail or {}}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            # errors()의 ctx에 예외 객체가 들어 있으면 그대로는 JSON으로 바꿀 수 없다
            content=error_body(
                "VALIDATION_ERROR", "요청 값을 확인해 주세요.", {"errors": jsonable_encoder(exc.errors())}
            ),
        )
