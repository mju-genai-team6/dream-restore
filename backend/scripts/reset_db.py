"""로컬 DB를 비우고 마이그레이션과 샘플 데이터를 다시 넣는다 (C2).

실행: backend 폴더에서  python scripts/reset_db.py        (확인 질문에 y)
      확인 없이:          python scripts/reset_db.py --yes
      샘플 없이 빈 DB만:  python scripts/reset_db.py --yes --no-seed

DATABASE_URL의 모든 테이블과 데이터가 지워진다. 안전을 위해
APP_ENV=local이고 DB 주소가 localhost(127.0.0.1)일 때만 실행된다.
"""

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import settings

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}  # db: docker compose 안에서 실행할 때


def _check_local(url: str) -> None:
    host = make_url(url).host
    if settings.app_env != "local" or host not in LOCAL_HOSTS:
        sys.exit(f"로컬 DB에서만 실행할 수 있습니다. (APP_ENV={settings.app_env}, host={host})")


def reset(url: str, *, with_seed: bool) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    engine.dispose()
    print("테이블을 모두 지웠습니다.")

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    print("마이그레이션을 끝까지 적용했습니다.")

    if with_seed:
        _load_seed().main()


def _load_seed():
    """scripts/는 패키지가 아니므로 seed.py를 파일 경로로 불러온다."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("seed", Path(__file__).with_name("seed.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="로컬 DB 초기화")
    parser.add_argument("--yes", action="store_true", help="확인 질문 없이 실행")
    parser.add_argument("--no-seed", action="store_true", help="샘플 데이터를 넣지 않음")
    args = parser.parse_args()

    url = settings.database_url
    _check_local(url)
    if not args.yes:
        answer = input(f"{make_url(url).render_as_string(hide_password=True)} 의 데이터를 모두 지웁니다. 계속할까요? [y/N] ")
        if answer.strip().lower() != "y":
            print("취소했습니다.")
            return
    reset(url, with_seed=not args.no_seed)


if __name__ == "__main__":
    main()
