"""라우터 공통 의존성."""
from fastapi import Response

MOCK_HEADERS = {"X-Mock": "true"}


def mark_mock(response: Response) -> None:
    """목업 응답 표시. 실제 처리로 바뀐 라우터에서는 제거한다."""
    response.headers.update(MOCK_HEADERS)
