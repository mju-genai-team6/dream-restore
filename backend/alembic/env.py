from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  모델을 등록해 autogenerate가 인식하도록 함
from alembic import context
from app.core.config import settings
from app.db.base import Base

config = context.config
# 기본은 개발 DB. 테스트(conftest.py)는 config.attributes["database_url"]로 dream_test를 넘깁니다.
database_url = config.attributes.get("database_url") or settings.database_url
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
