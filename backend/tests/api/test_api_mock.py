"""S1~S3 목업 API 계약 테스트 (C-S1-01)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import events as event_service
from app.services import mock_data

client = TestClient(app)

JSON_CASES = [
    ("get", "/dreams", {}, 200, mock_data.DREAM_LIST),
    ("get", "/dreams/1/scenes", {}, 200, mock_data.SCENES),
    ("post", "/dreams/1/renders", {}, 202, mock_data.RENDER_CREATED),
    ("get", "/dreams/1/renders/latest", {}, 200, mock_data.RENDER),
]


def _normalize(data: dict) -> dict:
    """응답의 datetime 표기(+09:00 등) 차이를 없애기 위해 키 구조만 비교한다."""
    if isinstance(data, dict):
        return {k: _normalize(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_normalize(v) for v in data]
    return None


@pytest.mark.parametrize(("method", "path", "kwargs", "status_code", "sample"), JSON_CASES)
def test_mock_endpoint_returns_sample_with_mock_header(method, path, kwargs, status_code, sample):
    res = client.request(method.upper(), path, **kwargs)

    assert res.status_code == status_code, res.text
    assert res.headers["X-Mock"] == "true"
    assert _normalize(res.json()) == _normalize(sample)


def test_events_stream_sends_sample_job_events_and_closes(monkeypatch):
    monkeypatch.setattr(event_service, "MOCK_EVENT_INTERVAL_SECONDS", 0)

    with client.stream("GET", "/dreams/1/events") as res:
        assert res.status_code == 200
        assert res.headers["X-Mock"] == "true"
        assert res.headers["content-type"].startswith("text/event-stream")
        data_lines = [line for line in res.iter_lines() if line.startswith("data:")]

    events = [json.loads(line.removeprefix("data:").strip()) for line in data_lines]
    assert [(e["status"], e["stage"]) for e in events] == [
        ("queued", None),
        ("running", "splitting"),
        ("running", "prompting"),
        ("succeeded", "prompting"),
    ]


@pytest.mark.parametrize(
    "path", ["/dreams/999", "/dreams/999/interview", "/dreams/999/events", "/jobs/999"]
)
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
