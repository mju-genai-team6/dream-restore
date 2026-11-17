from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DreamStatus, InputType
from app.db.base import (
    Base,
    CreatedAtMixin,
    IdMixin,
    TimestampMixin,
    enum_check,
    relative_path_check,
)

# 이관 문서 2장: mime_type CHECK(webm, mp4, m4a)
AUDIO_MIME_TYPES = ("audio/webm", "audio/mp4", "audio/x-m4a")


class Dream(IdMixin, TimestampMixin, Base):
    """꿈 기록 1건."""

    __tablename__ = "dreams"
    __table_args__ = (enum_check("input_type", InputType), enum_check("status", DreamStatus))

    input_type: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), server_default=DreamStatus.RECORDED.value)
    raw_text: Mapped[str | None] = mapped_column(Text)
    confirmed_text: Mapped[str | None] = mapped_column(Text)


# 꿈 일기 목록(최신순)
Index("ix_dreams_created_at_desc", Dream.created_at.desc())


class AudioFile(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "audio_files"
    __table_args__ = (
        CheckConstraint(f"mime_type IN ({', '.join(repr(m) for m in AUDIO_MIME_TYPES)})", name="mime_type"),
        relative_path_check("path"),
    )

    dream_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(500))  # storage/ 기준 상대 경로
    mime_type: Mapped[str] = mapped_column(String(50))
    size: Mapped[int] = mapped_column(BigInteger)  # 바이트
    duration: Mapped[float | None] = mapped_column(Float)  # 초
