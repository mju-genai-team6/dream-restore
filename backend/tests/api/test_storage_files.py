"""/storage 파일 제공 (C-S3-06). conftest가 /storage를 테스트별 임시 폴더(tmp_path)로 바꿔 둔다.

httpx는 인코딩하지 않은 ../를 보내기 전에 정리하므로, 서버까지 가는 인코딩된 형태로 확인한다.
"""
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def secret(tmp_path: Path) -> Iterator[Path]:
    """storage(tmp_path) 바로 바깥에 둔 파일."""
    path = tmp_path.parent / f"{tmp_path.name}-secret.txt"
    path.write_text("SECRET")
    yield path
    path.unlink(missing_ok=True)


def test_serves_file_inside_storage(tmp_path: Path):
    (tmp_path / "dreams").mkdir()
    (tmp_path / "dreams" / "ok.txt").write_text("ok")

    res = client.get("/storage/dreams/ok.txt")

    assert res.status_code == 200
    assert res.text == "ok"


_ANSWER = '{"video_1": "blur"}'


def _missing_file():
    return client.get("/storage/dreams/does-not-exist.txt")


def _eval_pair(tmp_path: Path) -> None:
    folder = tmp_path / "eval" / "p1_dream2"
    folder.mkdir(parents=True)
    (folder / "key.json").write_text(_ANSWER, encoding="utf-8")
    (folder / "video_1.mp4").write_bytes(b"video-1")
    (folder / "video_2.mp4").write_bytes(b"video-2")


def _assert_hidden_like_missing(url: str) -> None:
    missing = _missing_file()
    hidden = client.get(url)

    assert hidden.status_code == 404
    assert hidden.json() == missing.json() == {
        "error": {"code": "NOT_FOUND", "message": "파일을 찾을 수 없습니다.", "detail": {}}
    }
    assert hidden.headers["content-type"] == missing.headers["content-type"]
    assert _ANSWER not in hidden.text


def test_eval_answer_key_is_hidden_and_videos_stay_open(tmp_path: Path):
    _eval_pair(tmp_path)
    (tmp_path / "dreams").mkdir()
    (tmp_path / "dreams" / "ok.txt").write_text("ok")

    _assert_hidden_like_missing("/storage/eval/p1_dream2/key.json")
    assert client.head("/storage/eval/p1_dream2/key.json").status_code == 404

    video = client.get("/storage/eval/p1_dream2/video_1.mp4")
    assert video.status_code == 200
    assert video.content == b"video-1"
    video_2 = client.get("/storage/eval/p1_dream2/video_2.mp4")
    assert video_2.status_code == 200
    assert video_2.content == b"video-2"

    dream = client.get("/storage/dreams/ok.txt")
    assert dream.status_code == 200
    assert dream.text == "ok"


@pytest.mark.parametrize(
    "url",
    [
        "/storage/eval/p1_dream2/KEY.JSON",
        "/storage/EVAL/p1_dream2/key.json",
        "/storage/eval/p1_dream2%2Fkey.json",
        "/storage/eval/p1_dream2/%2e/key.json",
        "/storage/eval/p1_dream2/nested/%2e%2e/key.json",
        "/storage/dreams/%2e%2e/eval/p1_dream2/key.json",
    ],
)
def test_eval_answer_key_bypass_is_hidden(url: str, tmp_path: Path):
    _eval_pair(tmp_path)

    _assert_hidden_like_missing(url)


@pytest.mark.parametrize(
    "url",
    [
        "/storage/eval/p1_dream2/key.json.",
        "/storage/eval/p1_dream2/key.json%20",
        "/storage/eval/p1_dream2/key.json::$DATA",
    ],
)
def test_ntfs_alias_of_eval_key_is_not_served(url: str, tmp_path: Path):
    """끝 점·끝 공백·기본 데이터 스트림. Windows가 아니면 없는 파일이라 404다."""
    _eval_pair(tmp_path)

    assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "template",
    [
        "/storage/..%2F{name}",
        "/storage/%2e%2e/{name}",
        "/storage/%2e%2e%2f{name}",
        "/storage/..%5C{name}",
        "/storage/..\\{name}",
        "/storage/dreams/%2e%2e/%2e%2e/{name}",
        "/storage/{absolute}",
    ],
)
def test_path_outside_storage_is_not_served(template: str, secret: Path):
    url = template.format(name=secret.name, absolute=secret.as_posix())

    res = client.get(url)

    assert res.status_code == 404
    assert "SECRET" not in res.text
