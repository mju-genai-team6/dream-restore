"""테스트 DB 환경 자체를 확인하는 테스트 (C2)."""

from sqlalchemy import text


def test_uses_test_database(db):
    assert db.scalar(text("SELECT current_database()")) == "dream_test"


def test_commit_inside_test_is_rolled_back(db, db_engine):
    db.execute(text("CREATE TABLE _rollback_check (id int)"))
    db.execute(text("INSERT INTO _rollback_check VALUES (1)"))
    db.commit()  # SAVEPOINT까지만 확정

    assert db.scalar(text("SELECT count(*) FROM _rollback_check")) == 1

    # 바깥 트랜잭션은 아직 열려 있으므로 다른 연결에서는 보이지 않는다
    with db_engine.connect() as other:
        visible = other.scalar(text("SELECT to_regclass('public._rollback_check') IS NOT NULL"))
    assert visible is False
