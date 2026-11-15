"""S1~S3 목업 API 계약 테스트 (C-S1-01)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import events as event_service
from app.services import mock_data

client = TestClient(app)

JSON_CASES = [
    ("post", "/dreams", {"json": mock_data.DREAM_CREATE}, 201, mock_data.DREAM_CREATED),
    ("get", "/dreams", {}, 200, mock_data.DREAM_LIST),
    ("get", "/dreams/1", {}, 200, mock_data.DREAM),
    ("patch", "/dreams/1", {"json": mock_data.DREAM_CONFIRM}, 200, mock_data.DREAM_CONFIRMED),
    (
        "post",
        "/dreams/1/audio",
        {"files": {"file": ("dream.webm", b"fake", "audio/webm")}},
        201,
        mock_data.AUDIO_UPLOADED,
    ),
    ("get", "/dreams/1/interview", {}, 200, mock_data.INTERVIEW),
    ("post", "/dreams/1/interview", {"json": mock_data.ANSWER_CREATE}, 200, mock_data.ANSWER_SAVED),
    ("get", "/dreams/1/elements", {}, 200, mock_data.ELEMENTS),
    (
        "put",
        "/dreams/1/elements/confidence",
        {"json": mock_data.CONFIDENCE_UPDATE},
        200,
        mock_data.ELEMENTS,
    ),
    ("post", "/dreams/1/jobs", {"json": mock_data.JOB_CREATE}, 202, mock_data.JOB_CREATED),
    ("get", "/jobs/1", {}, 200, mock_data.JOB),
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


def test_confidence_update_reflects_requested_values():
    body = {"items": [{"element_id": 1, "confidence": "low"}]}
    res = client.put("/dreams/1/elements/confidence", json=body)

    elements = {e["element_id"]: e["confidence"] for e in res.json()["elements"]}
    assert elements[1] == "low"


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
