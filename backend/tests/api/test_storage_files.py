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
