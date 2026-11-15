"""서비스 트랜잭션 확정. repositories는 commit하지 않는다."""
from sqlalchemy.orm import Session


def commit(db: Session | None) -> None:
    """세션이 없으면(임시 저장소) 넘어간다. 실제 DB면 트랜잭션을 확정한다."""
    if db is None:
        return
    db.commit()


def rollback(db: Session | None) -> None:
    """세션이 없으면 넘어간다. 실제 DB면 트랜잭션을 되돌린다."""
    if db is None:
        return
    db.rollback()
