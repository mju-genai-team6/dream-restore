from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Confidence, JobStatus
from app.db.base import (
    Base,
    CreatedAtMixin,
    IdMixin,
    TimestampMixin,
    enum_check,
    relative_path_check,
)


class Scene(IdMixin, TimestampMixin, Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("dream_id", "order"),)

    dream_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"))
    order: Mapped[int] = mapped_column(Integer)
    # scene_versions와 서로 참조하므로 FK는 테이블 생성 후 따로 건다 (use_alter)
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("scene_versions.id", ondelete="SET NULL", use_alter=True)
    )
    # 조회용. 현재 버전을 바꿀 때는 current_version_id를 바꾼다 (repositories.scenes.set_current_version)
    current_version: Mapped["SceneVersion | None"] = relationship(
        foreign_keys=[current_version_id], viewonly=True
    )


class SceneVersion(IdMixin, TimestampMixin, Base):
    """장면 버전. 수정은 새 행으로 추가하고 기존 행은 바꾸지 않는다.

    DB 트리거(scene_versions_guard)가 지킨다:
    - scene_id, version_no, summary_ko, prompt_en, element_ids는 바꿀 수 없다.
    - final_prompt, model, settings, seed, image_path, generated_at, confidence_level은
      비어 있을 때 한 번만 채울 수 있다 (이미지 생성 결과·장면 확신도).
    - status는 바꿀 수 있다.
    """

    __tablename__ = "scene_versions"
    __table_args__ = (
        UniqueConstraint("scene_id", "version_no"),
        enum_check("confidence_level", Confidence),
        enum_check("status", JobStatus),
        relative_path_check("image_path"),
    )

    scene_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scenes.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    summary_ko: Mapped[str] = mapped_column(Text)
    prompt_en: Mapped[str] = mapped_column(Text)
    final_prompt: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    settings: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    seed: Mapped[int | None] = mapped_column(BigInteger)
    image_path: Mapped[str | None] = mapped_column(String(500))  # storage/ 기준 상대 경로
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 이미지 생성 완료 시각 (E2 요청)
    element_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), server_default="{}")
    confidence_level: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), server_default=JobStatus.QUEUED.value)


class Render(IdMixin, TimestampMixin, Base):
    """영상. scene_version_ids는 렌더 시작 시 고정하고 이후 바꾸지 않는다 (DB 트리거 renders_guard)."""

    __tablename__ = "renders"
    __table_args__ = (enum_check("status", JobStatus), relative_path_check("video_path"))

    dream_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), server_default=JobStatus.QUEUED.value)
    video_path: Mapped[str | None] = mapped_column(String(500))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[float | None] = mapped_column(Float)
    scene_version_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    postprocess_settings: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class Narration(IdMixin, CreatedAtMixin, Base):
    """(선택) 나레이션."""

    __tablename__ = "narrations"
    __table_args__ = (relative_path_check("audio_path"),)

    scene_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scene_versions.id", ondelete="CASCADE"), index=True
    )
    audio_path: Mapped[str] = mapped_column(String(500))
    duration: Mapped[float | None] = mapped_column(Float)
