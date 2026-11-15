from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Confidence, ElementType, ExtractionPhase
from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampMixin, enum_check


class Extraction(IdMixin, CreatedAtMixin, Base):
    """요소 추출 결과. raw(원문 추출)와 after_interview(인터뷰 반영 추출)를 모두 남긴다."""

    __tablename__ = "extractions"
    __table_args__ = (enum_check("phase", ExtractionPhase),)

    dream_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"), index=True)
    phase: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONB)
    element_count: Mapped[int] = mapped_column(Integer)
    text_length: Mapped[int] = mapped_column(Integer)


class DreamElement(IdMixin, TimestampMixin, Base):
    """추출된 요소. 확신도는 사용자 입력만 저장하고, 입력 전에는 NULL."""

    __tablename__ = "dream_elements"
    __table_args__ = (enum_check("type", ElementType), enum_check("confidence", Confidence))

    dream_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"), index=True)
    extraction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("extractions.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, server_default="")
    confidence: Mapped[str | None] = mapped_column(String(10))
    entity_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("world_entities.id", ondelete="SET NULL"), index=True
    )


class InterviewQuestion(IdMixin, TimestampMixin, Base):
    """되묻기 질문. "기억 안 남"은 skipped=True."""

    __tablename__ = "interview_questions"
    __table_args__ = (UniqueConstraint("dream_id", "order"),)

    dream_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"))
    order: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    target_element: Mapped[str | None] = mapped_column(String(50))
    answer: Mapped[str | None] = mapped_column(Text)
    skipped: Mapped[bool] = mapped_column(Boolean, server_default="false")
