"""(선택) 세계관 인물·장소와 평가 응답. S4에서 API가 붙는다."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ElementType
from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampMixin

WORLD_ENTITY_KINDS = (ElementType.PERSON.value, ElementType.PLACE.value)


class WorldEntity(IdMixin, TimestampMixin, Base):
    """여러 꿈에 반복해 나오는 인물·장소. 외형 항목은 B2·E2와 맞춘다."""

    __tablename__ = "world_entities"
    __table_args__ = (CheckConstraint(f"kind IN ({', '.join(repr(k) for k in WORLD_ENTITY_KINDS)})", name="kind"),)

    name: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20))
    hair: Mapped[str | None] = mapped_column(String(200))
    outfit: Mapped[str | None] = mapped_column(String(200))
    age_range: Mapped[str | None] = mapped_column(String(50))
    features: Mapped[str | None] = mapped_column(Text)


class Evaluation(IdMixin, CreatedAtMixin, Base):
    """5점 척도 평가 응답 (E1 확신도 평가, E2 인물 일관성 평가)."""

    __tablename__ = "evaluations"
    __table_args__ = (CheckConstraint("score BETWEEN 1 AND 5", name="score"),)

    dream_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"), index=True)
    render_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("renders.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # 평가 종류. 값은 E1·E2와 확정 후 CHECK 추가
    condition: Mapped[str] = mapped_column(String(50))  # 비교 조건 (예: 블러 적용/미적용)
    score: Mapped[int] = mapped_column(SmallInteger)
