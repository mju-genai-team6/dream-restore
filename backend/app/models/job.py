from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import FailureCode, JobStage, JobStatus, JobType
from app.db.base import Base, IdMixin, TimestampMixin, enum_check

ACTIVE_JOB_STATUSES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


class Job(IdMixin, TimestampMixin, Base):
    """작업. 꿈 기록 상태와 별도로 관리한다 (docs/rules/job-status.md)."""

    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("type", JobType),
        enum_check("status", JobStatus),
        enum_check("stage", JobStage),
        enum_check("error_code", FailureCode),
        # 진행 중 작업 중복 방지: (dream_id, type, target_id)에 status가 queued·running일 때만 적용.
        # target_id가 NULL인 작업끼리도 같은 것으로 본다 (NULLS NOT DISTINCT)
        Index(
            "uq_jobs_active",
            "dream_id",
            "type",
            "target_id",
            unique=True,
            postgresql_where=text(f"status IN ({', '.join(repr(s) for s in ACTIVE_JOB_STATUSES)})"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    dream_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), server_default=JobStatus.QUEUED.value)
    stage: Mapped[str | None] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
