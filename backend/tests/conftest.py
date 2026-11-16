"""DB 테스트 공통 설정 (C2).

- 테스트는 개발 DB(dream)가 아니라 TEST_DATABASE_URL(dream_test)을 씁니다.
- 세션 시작 시 dream_test가 없으면 만들고, alembic upgrade head로 스키마를 맞춥니다.
- `db` fixture는 테스트마다 트랜잭션을 열고 끝나면 되돌립니다.
  테스트 안에서 db.commit()을 불러도 SAVEPOINT까지만 확정되므로 다음 테스트에 남지 않습니다.
- DB가 떠 있지 않으면(docker compose up -d db 전) DB 테스트만 skip되고 나머지는 그대로 돕니다.

사용 예:
    def test_create_dream(db):
        dream = dreams.create_dream(db, ...)
        assert dream.id is not None
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _ensure_test_database(url: str) -> None:
    """dream_test가 없으면 같은 서버의 postgres DB에 접속해 만든다."""
    target = make_url(url)
    if target.database == make_url(settings.database_url).database:
        raise RuntimeError("TEST_DATABASE_URL이 개발 DB와 같습니다. 테스트가 개발 데이터를 지울 수 있어 중단합니다.")

    # Windows에서는 DB가 꺼져 있으면 연결이 거절되지 않고 오래 멈추므로 짧게 끊는다
    admin = create_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
    )
    try:
        with admin.connect() as conn:
            exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database})
            if not exists:
                conn.exec_driver_sql(f'CREATE DATABASE "{target.database}"')
    finally:
        admin.dispose()


def _upgrade_to_head(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    url = settings.test_database_url
    try:
        _ensure_test_database(url)
    except OperationalError as exc:
        pytest.skip(f"테스트 DB에 연결할 수 없습니다. `docker compose up -d db`를 먼저 실행하세요. ({exc.orig})")

    _upgrade_to_head(url)
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine: Engine) -> Iterator[Session]:
    """테스트 하나 동안 쓰는 세션. 끝나면 모든 변경을 되돌린다."""
    connection = db_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()
