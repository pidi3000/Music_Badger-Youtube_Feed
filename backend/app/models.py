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

    backfill_days: Mapped[int] = mapped_column(Integer, default=365)
    backfill_min_count: Mapped[int] = mapped_column(Integer, default=50)

    # How many days back an incremental update keeps paginating a channel's
    # uploads playlist looking for new videos, before giving up for this run
    # (mirrors BackfillTask.target_after but is independently configurable —
    # updates are meant to be quick, backfill is meant to be thorough).
    update_lookback_days: Mapped[int] = mapped_column(Integer, default=30)

    # When every API key is exhausted, fall back to RSS for updates (fewer
    # items, no Shorts/Live classification) instead of stalling. Channels
    # updated this way are re-checked via the API on the next run once quota
    # is available again — see app.services.update_service.
    rss_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Off by default: when on, any upload of 3 minutes or less gets an extra,
    # unofficial check (app.services.youtube_client._is_actual_short) to
    # tell an actual Short from a merely-short video by aspect ratio, since
    # the Data API doesn't expose that for videos you don't own. Costs no
    # API quota (it's a plain web request, not a Data API call) but adds one
    # extra HTTP request per candidate video and relies on undocumented
    # YouTube redirect behavior — see PROJECT_OUTLINE.md.
    strict_shorts_detection: Mapped[bool] = mapped_column(Boolean, default=False)

    # Seeded from Config.sync_interval_minutes / .backfill_worker_interval_seconds
    # on first boot, then editable from Settings — see app.scheduler for how a
    # change here live-reschedules the running APScheduler jobs.
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    backfill_worker_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)

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

    # The actual date the user subscribed on YouTube (subscriptions.list
    # snippet.publishedAt), set on subscription import. Null for
    # manual-only channels, which have no such date.
    subscribed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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

    # "video" | "short" | "live" — best-effort classification (duration +
    # live-broadcast status via the Data API; RSS-sourced uploads can't be
    # classified without an extra API call, so they default to "video").
    video_type: Mapped[str] = mapped_column(String(8), default="video")

    # True only when video_type was confirmed by the strict-mode
    # youtube.com/shorts/{id} redirect check (AppSettings.strict_shorts_detection),
    # not just guessed from duration. False for the duration heuristic,
    # live videos, and anything fetched before strict mode was enabled.
    video_type_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    channel: Mapped["Channel"] = relationship(back_populates="uploads")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(255))
    key_value_encrypted: Mapped[str] = mapped_column(Text)

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


class UpdateTask(Base):
    """Resumable per-channel incremental upload sync task — mirrors
    BackfillTask's lifecycle (queued/in_progress/paused_quota/completed/
    failed with a resume_cursor for pagination continuation across quota
    pauses) but paginates only until a page yields no new uploads or the
    oldest fetched upload crosses AppSettings.update_lookback_days, rather
    than backfill's much deeper target. See app.services.update_service."""

    __tablename__ = "update_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)

    # "queued" | "in_progress" | "paused_quota" | "completed" | "failed"
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)

    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    # Opaque pagination resume point (a YouTube pageToken).
    resume_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oldest_fetched_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # True once this run has fallen back to RSS because every API key was
    # exhausted — flags the channel to be rechecked via the API on the next
    # update once quota is available again.
    used_rss_fallback: Mapped[bool] = mapped_column(Boolean, default=False)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    channel: Mapped["Channel"] = relationship()


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
