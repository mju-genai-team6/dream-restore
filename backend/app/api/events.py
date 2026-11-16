"""진행 상태 SSE GET /dreams/{id}/events (S2). 사용: B2"""
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.api.deps import MOCK_HEADERS
from app.schemas.common import error_responses
from app.services import events as event_service

router = APIRouter(prefix="/dreams", tags=["events"])

_SSE_EXAMPLE = (
    'event: job\ndata: {"job_id":1,"type":"generate_scenes","status":"queued","stage":null}\n\n'
    'event: job\ndata: {"job_id":1,"type":"generate_scenes","status":"running",'
    '"stage":"splitting"}\n\n'
)


@router.get(
    "/{dream_id}/events",
    response_class=EventSourceResponse,
    summary="진행 상태 수신 (SSE, 작업 상태·단계만 전송)",
    responses={
        200: {
            "description": "event: job, data: JobSummary JSON",
            "content": {"text/event-stream": {"example": _SSE_EXAMPLE}},
        },
        **error_responses(404),
    },
)
def stream_events(dream_id: int) -> EventSourceResponse:
    # Response 객체를 직접 반환하면 의존성의 헤더가 합쳐지지 않아 직접 붙인다.
    return EventSourceResponse(event_service.stream_job_events(dream_id), headers=MOCK_HEADERS)
