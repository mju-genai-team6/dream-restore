"""S1~S3 API 계약 테스트 (C-S1-01)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_mock_sse_endpoint_is_removed():
    """SSE 없이 주기적 조회만 쓴다 (C-S2-05)."""
    assert client.get("/dreams/1/events").status_code == 404
    assert not any(path.endswith("/events") for path in app.openapi()["paths"])


@pytest.mark.parametrize("path", ["/dreams/999", "/dreams/999/interview", "/jobs/999"])
def test_unknown_id_returns_not_found_error_format(path):
    res = client.get(path)

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/dreams", {"input_type": "text"}),
        ("/dreams/1/interview", {"question_id": 1}),
        ("/dreams/1/jobs", {"type": "render_video"}),
        ("/dreams/1/elements/confidence", {"items": [{"element_id": 1, "confidence": "x"}]}),
    ],
)
def test_invalid_body_returns_validation_error(path, body):
    method = "PUT" if path.endswith("confidence") else "POST"
    res = client.request(method, path, json=body)

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_validation_error_with_exception_in_ctx_is_not_500():
    """검증기가 ValueError를 던지면 errors()의 ctx에 예외 객체가 들어간다."""
    from fastapi import FastAPI
    from pydantic import BaseModel, field_validator

    from app.core.errors import register_error_handlers

    class Body(BaseModel):
        value: int

        @field_validator("value")
        @classmethod
        def _reject(cls, value: int) -> int:
            raise ValueError("허용하지 않는 값")

    probe = FastAPI()
    register_error_handlers(probe)

    @probe.post("/probe")
    def _probe(body: Body) -> dict:
        return {}

    res = TestClient(probe, raise_server_exceptions=False).post("/probe", json={"value": 1})

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
