import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router as api_router
from app.core.config import settings
from app.core.errors import AudioTooLarge, error_body, register_error_handlers
from app.jobs import runner
from app.jobs.handlers.images import install_image_handler
from app.storage.files import StorageFiles

# uvicorn이 핸들러를 붙여 둔 로거. app 로거의 INFO는 로깅 설정이 없어 출력되지 않는다
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    install_image_handler(settings.image_generation_mode)
    logger.info("이미지 생성 모드: %s", settings.image_generation_mode)
    # 재시작 전 BackgroundTasks의 작업은 사라졌으므로 running·queued로 남은 작업을 실패 처리한다
    runner.recover_interrupted()
    yield


app = FastAPI(title="Dream Restore API", version="0.1.0", lifespan=lifespan)

_AUDIO_UPLOAD_PATH = re.compile(r"^/dreams/\d+/audio$")
_MULTIPART_MARGIN_BYTES = 1024 * 1024


# CORSMiddleware보다 먼저 등록해야 CORS가 바깥에 있어 413 응답에도 CORS 헤더가 붙는다
@app.middleware("http")
async def reject_large_audio(request: Request, call_next):
    """Content-Length만 보고 본문을 읽기 전에 거른다. 헤더가 없거나 틀린 요청은 핸들러가 복사 중에 거른다."""
    if request.method == "POST" and _AUDIO_UPLOAD_PATH.match(request.url.path):
        length = request.headers.get("content-length", "")
        limit = settings.audio_max_mb * 1024 * 1024 + _MULTIPART_MARGIN_BYTES
        if length.isdigit() and int(length) > limit:
            return JSONResponse(
                status_code=AudioTooLarge.status_code,
                content=error_body(
                    AudioTooLarge.code,
                    f"음성 파일은 {settings.audio_max_mb}MB까지 올릴 수 있습니다.",
                    {"max_mb": settings.audio_max_mb},
                ),
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(api_router)

settings.storage_path.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StorageFiles(directory=settings.storage_path), name="storage")


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
