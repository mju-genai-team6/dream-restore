"""완료 기준: 빈 DB에서 alembic upgrade head가 한 번에 성공하고 downgrade도 동작한다.

dream_test와 별도의 빈 DB(dream_migration_test)를 만들어 확인하고 끝나면 지운다.
"""

from collections.abc import Iterator

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import settings
from tests.conftest import BACKEND_DIR

TABLES = {
    "dreams", "audio_files", "extractions", "dream_elements", "interview_questions", "jobs",
    "scenes", "scene_versions", "renders", "narrations", "world_entities", "evaluations",
}
VIEWS = {"v_interview_comparison", "v_confidence_evaluation", "v_character_consistency", "v_processing_time"}


@pytest.fixture
def empty_db_url(db_engine) -> Iterator[str]:
    """빈 DB를 새로 만들고 URL을 돌려준다. db_engine에 의존해 DB가 꺼져 있으면 skip된다."""
    url = make_url(settings.test_database_url).set(database="dream_migration_test")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql('DROP DATABASE IF EXISTS "dream_migration_test" WITH (FORCE)')
        conn.exec_driver_sql('CREATE DATABASE "dream_migration_test"')
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql('DROP DATABASE IF EXISTS "dream_migration_test" WITH (FORCE)')
        admin.dispose()


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    return cfg


def _snapshot(url: str) -> tuple[set[str], set[str], str | None]:
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        with engine.connect() as conn:
            version = conn.scalar(text("SELECT version_num FROM alembic_version")) if insp.has_table("alembic_version") else None
        return set(insp.get_table_names()) - {"alembic_version"}, set(insp.get_view_names()), version
    finally:
        engine.dispose()


def test_upgrade_head_then_downgrade_on_empty_db(empty_db_url):
    cfg = _config(empty_db_url)
    head = ScriptDirectory.from_config(cfg).get_current_head()

    command.upgrade(cfg, "head")  # 빈 DB에서 한 번에
    tables, views, version = _snapshot(empty_db_url)
    assert tables == TABLES
    assert views == VIEWS
    assert version == head

    command.downgrade(cfg, "-1")  # 마지막 단계 되돌리기
    command.upgrade(cfg, "head")  # 다시 올라가는지

    command.downgrade(cfg, "base")  # 끝까지 되돌리면 테이블·뷰가 모두 사라진다
    tables, views, version = _snapshot(empty_db_url)
    assert tables == set()
    assert views == set()
    assert version is None
