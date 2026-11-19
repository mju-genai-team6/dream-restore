"""C API 테스트 공통 설정. 실제 PostgreSQL 테스트 DB(dream_test)를 쓴다.

- `db_engine`은 tests/conftest.py(DB 담당)의 것을 그대로 쓴다. DB가 꺼져 있으면 이 폴더의 테스트는 skip된다.
- API는 요청마다 새 세션을 열고 실제로 commit한다. 동시 요청과 "commit이 정말 됐는지"를 다른 연결에서
  확인해야 하므로, 트랜잭션 되돌리기 대신 테스트 전후에 테이블을 비운다(id도 1부터 다시 시작).
- `read_db`는 검증용 별도 연결이다. 다른 세션이 commit한 데이터만 보인다. 이미 읽은 객체를
  API 호출 뒤 다시 확인할 때는 `read_db.expire_all()`을 먼저 부른다.
"""
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from app.core.config import settings
from app.core.enums import JobType
from app.db.session import get_db
from app.jobs import runner
from app.jobs.handlers.images import fake_generate_image
from app.jobs.registry import HANDLERS
from app.main import app

# 나머지 테이블은 모두 dreams나 world_entities에 딸려 있어 CASCADE로 함께 비워진다
_TRUNCATE = "TRUNCATE dreams, world_entities RESTART IDENTITY CASCADE"


def _truncate(engine: Engine) -> None:
    with engine.begin() as conn:
        # 앞 테스트의 연결이 잠금을 쥐고 남아 있으면 멈추지 않고 바로 실패한다
        conn.execute(text("SET LOCAL lock_timeout = '3s'"))
        conn.execute(text(_TRUNCATE))


@pytest.fixture
def session_factory(db_engine: Engine) -> sessionmaker[Session]:
    """앱(app/db/session.py)과 같은 설정의 세션. `with session_factory.begin() as s:`는 끝에서 commit한다."""
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def no_real_image_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """.env에 키가 있어도 pytest가 실제 이미지 API를 부르지 않게 한다.

    키를 비우고 이미지 생성 모드를 fake로 고정한 뒤 generate_image에 가짜 핸들러를 끼운다.
    setitem이라 lifespan(install_image_handler)이 바꾼 핸들러도 테스트가 끝나면 되돌아간다.
    가짜 핸들러가 쓰는 파일은 테스트별 임시 폴더에 둔다. /storage 마운트는 import 때 경로로 고정되므로
    같은 임시 폴더를 보도록 함께 바꾼다.
    """
    for name in ("OPENAI_API_KEY", "IMAGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "image_api_key", "")
    monkeypatch.setattr(settings, "image_generation_mode", "fake")
    monkeypatch.setitem(HANDLERS, JobType.GENERATE_IMAGE, fake_generate_image)
    monkeypatch.setattr(settings, "storage_path", tmp_path)  # cached_property라 값을 직접 바꾼다
    static = _storage_files()
    monkeypatch.setattr(static, "directory", tmp_path)
    monkeypatch.setattr(static, "all_directories", [tmp_path])


def _storage_files() -> StaticFiles:
    return next(route.app for route in app.routes if isinstance(route, Mount) and route.name == "storage")


@pytest.fixture(autouse=True)
def api_db(
    db_engine: Engine, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """API의 get_db를 테스트 DB 세션으로 바꾸고 테스트 전후에 테이블을 비운다.

    tests/conftest.py의 _api_uses_stub_session(get_db → None)보다 나중에 실행되어 그 설정을 덮어쓴다.
    작업 실행기와 서버 시작 처리(lifespan)도 같은 테스트 DB 세션을 쓰고, 대기 시간은 0으로 둔다.
    """
    monkeypatch.setattr(runner, "session_factory", session_factory)
    monkeypatch.setattr(settings, "job_retry_delay_seconds", 0)
    _truncate(db_engine)

    def _get_test_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)
    _truncate(db_engine)


@pytest.fixture
def read_db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as db:
        yield db
