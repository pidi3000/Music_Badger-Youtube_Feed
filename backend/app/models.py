"""SQLAlchemy 2.0 ORM models. See PROJECT_OUTLINE.md §4 for the design.

All timestamps are stored UTC-naive (interpreted as UTC) via
`datetime.utcnow` defaults for SQLite/Postgres portability.
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class AppSettings(Base):
    """Single-row table of app-wide, user-editable settings.

    A row is created on first boot (see app.services.settings_bootstrap).
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    access_secret_hash: Mapped[str] = mapped_column(String(255))

    upload_fetch_method: Mapped[str] = mapped_column(String(8), default="api")
    backfill_days: Mapped[int] = mapped_column(Integer, default=365)
    backfill_min_count: Mapped[int] = mapped_column(Integer, default=50)

    # Encrypted (app.encryption) YouTube OAuth refresh token, if connected.
    youtube_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    youtube_channel_title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "subscription" | "manual" | "both"
    source: Mapped[str] = mapped_column(String(16), default="manual")

    # "subscribed" | "unsubscribed"
    subscription_status: Mapped[str] = mapped_column(String(16), default="subscribed")
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unsubscribed_ack: Mapped[bool] = mapped_column(Boolean, default=False)

    # Per-channel override of AppSettings.upload_fetch_method. Null = use default.
    upload_fetch_method: Mapped[str | None] = mapped_column(String(8), nullable=True)

    backfill_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    uploads: Mapped[list["Upload"]] = relationship(back_populates="channel", cascade="all, delete-orphan")
    channel_tags: Mapped[list["ChannelTag"]] = relationship(back_populates="channel", cascade="all, delete-orphan")
    backfill_tasks: Mapped[list["BackfillTask"]] = relationship(back_populates="channel", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    color: Mapped[str] = mapped_column(String(7), default="#6b7280")  # hex color

    channel_tags: Mapped[list["ChannelTag"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class ChannelTag(Base):
    __tablename__ = "channel_tags"
    __table_args__ = (UniqueConstraint("channel_id", "tag_id", name="uq_channel_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"))

    channel: Mapped["Channel"] = relationship(back_populates="channel_tags")
    tag: Mapped["Tag"] = relationship(back_populates="channel_tags")


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (UniqueConstraint("channel_id", "youtube_video_id", name="uq_channel_video"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(512))
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "api" | "rss" — how this row's data was sourced (transparency, §4)
    fetched_via: Mapped[str] = mapped_column(String(8))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    channel: Mapped["Channel"] = relationship(back_populates="uploads")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(255))
    key_value_encrypted: Mapped[str] = mapped_column(Text)

    # "background" | "active"
    group: Mapped[str] = mapped_column(String(16))
    # "active" | "exhausted" | "disabled"
    status: Mapped[str] = mapped_column(String(16), default="active")

    quota_resets_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BackfillTask(Base):
    __tablename__ = "backfill_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)

    # "queued" | "in_progress" | "paused_quota" | "completed" | "failed"
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)

    target_min_count: Mapped[int] = mapped_column(Integer)
    target_after: Mapped[date] = mapped_column(Date)

    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    # Opaque pagination resume point (a YouTube pageToken).
    resume_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oldest_fetched_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    channel: Mapped["Channel"] = relationship(back_populates="backfill_tasks")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # "running" | "success" | "error"
    status: Mapped[str] = mapped_column(String(16), default="running")

    channels_added: Mapped[int] = mapped_column(Integer, default=0)
    channels_marked_unsubscribed: Mapped[int] = mapped_column(Integer, default=0)
    rss_fallback_channels: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
