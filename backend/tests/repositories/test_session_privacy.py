"""앱 DB 엔진이 오류 메시지에 SQL 바인딩 값(꿈 원문)을 남기지 않는지 확인한다.

주의: hide_parameters는 SQLAlchemy가 붙이는 [parameters: ...] 부분만 숨긴다.
CHECK·NOT NULL 위반 때 PostgreSQL이 보내는 "DETAIL: Failing row contains (...)"에는
행 전체(원문 포함)가 들어 있어 이 설정으로는 숨겨지지 않는다. 로그를 남기는 쪽에서 걸러야 한다.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models import Dream

SECRET = "비밀스러운 꿈 원문 문장"


def test_app_engine_hides_parameters():
    assert engine.hide_parameters is True


def _check_violation(url, **engine_kwargs) -> IntegrityError:
    """CHECK 제약 위반을 일으켜 예외를 돌려준다 (rollback되어 데이터는 남지 않음)."""
    test_engine = create_engine(url, **engine_kwargs)
    try:
        with Session(test_engine) as s, pytest.raises(IntegrityError) as excinfo:
            s.add(Dream(input_type="text", status="not_a_status", raw_text=SECRET))
            s.flush()
        return excinfo.value
    finally:
        test_engine.dispose()


def test_sql_parameters_are_hidden(db_engine):
    hidden = str(_check_violation(db_engine.url, hide_parameters=True))
    assert "[SQL parameters hidden due to hide_parameters=True]" in hidden
    assert "[parameters:" not in hidden

    # 설정이 없으면 바인딩 값이 그대로 찍힌다 (설정이 실제로 효과가 있는지 비교)
    assert "[parameters:" in str(_check_violation(db_engine.url))


def test_postgres_detail_still_contains_row(db_engine):
    """hide_parameters로 막을 수 없는 부분을 기록해 둔다. 로그 쪽에서 detail을 빼야 한다."""
    exc = _check_violation(db_engine.url, hide_parameters=True)
    assert SECRET in (exc.orig.diag.message_detail or "")
    assert SECRET not in exc.orig.diag.message_primary  # 첫 줄(오류 요약)에는 원문이 없다
    assert exc.orig.sqlstate == "23514"  # check_violation
