"""모델 공통 규칙 (C2). docs/rules/data-model.md 참고.

- 기본키: 자동 증가 bigint (storage/paths.py가 정수 id를 씀)
- 시간: 모든 테이블에 created_at, 값이 바뀌는 테이블에는 updated_at
- 상태·종류 값: PostgreSQL enum 대신 문자열 + CHECK. 값 목록은 app/core/enums.py에서 가져온다
- 제약 이름은 NAMING_CONVENTION으로 고정해 마이그레이션 downgrade에서 이름으로 지울 수 있게 한다
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimestampMixin(CreatedAtMixin):
    # onupdate는 ORM 수정과 Core update() 문 모두에 적용된다
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def relative_path_check(column: str) -> CheckConstraint:
    """storage/ 기준 상대 경로만 허용. /·\\로 시작, 드라이브 문자(C:), '..'가 들어간 경로는 거부.

    제약 이름은 ck_<테이블>_<column>_relative.
    """
    return CheckConstraint(
        f"{column} !~ '^[/\\\\]' AND {column} !~ '^[A-Za-z]:' AND {column} NOT LIKE '%..%'",
        name=f"{column}_relative",
    )


def enum_check(column: str, enum_cls: type[StrEnum], name: str | None = None) -> CheckConstraint:
    """`column IN (enums.py의 값들)` CHECK 제약. 제약 이름은 ck_<테이블>_<name>."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name or column)
