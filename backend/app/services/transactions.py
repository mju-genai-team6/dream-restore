"""서비스 트랜잭션 확정. repositories는 commit하지 않는다."""
from sqlalchemy.orm import Session


def commit(db: Session) -> None:
    db.commit()


def rollback(db: Session) -> None:
    db.rollback()


def expire_loaded(db: Session) -> None:
    """세션에 불러 둔 객체를 버려 다음 조회가 DB에서 다시 읽게 한다.

    get_dream은 같은 세션에 이미 불러온 객체가 있으면 DB를 다시 읽지 않는다.
    잠금을 기다린 뒤 상태를 다시 확인할 때 부른다.
    """
    db.expire_all()
