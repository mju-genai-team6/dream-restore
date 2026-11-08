"""backend/app/llm 과 backend/worker/* 의 작업 함수 공통 규격.

    def handle(ctx: JobContext, payload: dict) -> dict:
        ctx.report_stage(JobStage.POSTPROCESSING)
        src = ctx.path_for("scene_original", scene_id=..., version_no=...)
        ...
        raise JobError(FailureCode.RENDER_FAILED, "FFmpeg 실행 실패")  # 실패 시
        return {"video_path": "...", "duration": 12.0}

BackgroundTasks에서 Redis 작업 큐로 바뀌어도 이 규격은 유지됩니다.
"""
import logging
from pathlib import Path
from typing import Protocol

from app.core.enums import FailureCode, JobStage


class JobError(Exception):
    def __init__(self, code: FailureCode, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class JobContext(Protocol):
    job_id: int
    dream_id: int
    logger: logging.Logger

    def report_stage(self, stage: JobStage) -> None:
        """처리 단계를 기록하고 SSE로 전송."""

    def path_for(self, kind: str, **ids) -> Path:
        """파일 경로 규칙에 따른 저장 위치 (app/storage/paths.py)."""

    def tmp_dir(self) -> Path:
        """작업 전용 임시 폴더. 검증 후 최종 경로로 옮긴다."""
