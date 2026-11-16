"""진행 상태 SSE 이벤트. 지금은 샘플 이벤트를 보내고 끝낸다."""
import asyncio
from collections.abc import AsyncIterator

from app.schemas.jobs import JobSummary
from app.services import mock_data
from app.services.dreams import ensure_sample_dream

MOCK_EVENT_INTERVAL_SECONDS = 0.5


def publish_job_event(summary: JobSummary) -> None:
    """실행기가 작업 상태·단계를 바꿀 때마다 부른다. 작업 스레드에서 불리므로 오래 막지 않는다."""
    # TODO(C-S2-05): 꿈별 구독자에게 전달


# TODO(C-S2-05): 실행기의 작업 상태·단계 변경을 구독해서 전송
def stream_job_events(dream_id: int) -> AsyncIterator[dict[str, str]]:
    """연결 전에 꿈 존재를 확인해야 404를 돌려줄 수 있어 생성기를 따로 만든다."""
    ensure_sample_dream(dream_id)
    return _mock_events()


async def _mock_events() -> AsyncIterator[dict[str, str]]:
    for event in mock_data.JOB_EVENTS:
        yield {"event": "job", "data": JobSummary.model_validate(event).model_dump_json()}
        await asyncio.sleep(MOCK_EVENT_INTERVAL_SECONDS)
