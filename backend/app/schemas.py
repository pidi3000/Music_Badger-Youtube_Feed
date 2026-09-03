"""Pydantic v2 request/response schemas — the exact JSON contract from
PROJECT_OUTLINE.md §8, kept in one module since API and frontend both need
to agree on it precisely.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FetchMethod = Literal["api", "rss"]
ApiKeyGroup = Literal["background", "active"]
ApiKeyStatus = Literal["active", "exhausted", "disabled"]
BackfillStatus = Literal["not_started", "queued", "in_progress", "paused_quota", "completed", "failed"]
SyncStatus = Literal["running", "success", "error"]


# ---------------------------------------------------------------- auth ----
class LoginRequest(BaseModel):
    secret: str


class OkResponse(BaseModel):
    ok: bool = True


class AuthStatus(BaseModel):
    authenticated: bool
    youtube_connected: bool


# ------------------------------------------------------------ settings ----
class SettingsOut(BaseModel):
    sync_interval_minutes: int
    backfill_worker_interval_seconds: int
    upload_fetch_method: FetchMethod
    backfill_days: int
    backfill_min_count: int
    strict_shorts_detection: bool
    youtube_connected: bool
    youtube_channel_title: str | None = None


class SettingsUpdate(BaseModel):
    sync_interval_minutes: int | None = Field(default=None, ge=1)
    backfill_worker_interval_seconds: int | None = Field(default=None, ge=10)
    upload_fetch_method: FetchMethod | None = None
    backfill_days: int | None = Field(default=None, ge=1)
    backfill_min_count: int | None = Field(default=None, ge=1)
    strict_shorts_detection: bool | None = None


class YoutubeAuthStart(BaseModel):
    authorization_url: str


# ----------------------------------------------------------------- tag ----
class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str


class TagCreate(BaseModel):
    name: str
    color: str = "#6b7280"


class TagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


# ------------------------------------------------------------- channel ----
class ChannelOut(BaseModel):
    id: int
    youtube_channel_id: str
    title: str
    handle: str | None
    thumbnail_url: str | None
    source: Literal["subscription", "manual", "both"]
    subscription_status: Literal["subscribed", "unsubscribed"]
    unsubscribed_at: datetime | None
    unsubscribed_ack: bool
    upload_fetch_method: FetchMethod | None
    effective_fetch_method: FetchMethod
    backfill_completed_at: datetime | None
    backfill_status: BackfillStatus
    upload_count: int
    oldest_upload_at: datetime | None
    latest_upload_at: datetime | None
    last_synced_at: datetime | None
    tags: list[TagOut]
    subscribed_at: datetime | None
    added_at: datetime
    updated_at: datetime


class ChannelCreate(BaseModel):
    channel_link: str
    tag_ids: list[int] = Field(default_factory=list)
    upload_fetch_method: FetchMethod | None = None


class ChannelUpdate(BaseModel):
    tag_ids: list[int] | None = None
    # Distinguishing "omitted" from "explicitly set to null" (clear the
    # per-channel override, fall back to the global default) requires
    # checking `model_fields_set` in the router rather than the value
    # itself — see app.api.channels.update_channel.
    upload_fetch_method: FetchMethod | None = None


# -------------------------------------------------------------- upload ----
VideoType = Literal["video", "short", "live"]


class ChannelRef(BaseModel):
    id: int
    title: str
    thumbnail_url: str | None
    youtube_channel_id: str
    handle: str | None


class UploadOut(BaseModel):
    id: int
    channel: ChannelRef
    youtube_video_id: str
    title: str
    published_at: datetime
    thumbnail_url: str | None
    fetched_via: FetchMethod
    video_type: VideoType


class FeedPage(BaseModel):
    items: list[UploadOut]
    next_cursor: str | None
    total_uploads: int


# ------------------------------------------------------------- api key ----
class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    group: ApiKeyGroup
    status: ApiKeyStatus
    quota_resets_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreate(BaseModel):
    label: str
    group: ApiKeyGroup
    key_value: str


class ApiKeyUpdate(BaseModel):
    label: str | None = None
    group: ApiKeyGroup | None = None
    status: Literal["active", "disabled"] | None = None


# -------------------------------------------------------------- backfill --
class BackfillTaskOut(BaseModel):
    id: int
    channel: ChannelRef
    status: Literal["queued", "in_progress", "paused_quota", "completed", "failed"]
    fetched_count: int
    target_min_count: int
    target_after: date
    oldest_fetched_published_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ sync --
class SyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: SyncStatus
    channels_added: int
    channels_marked_unsubscribed: int
    rss_fallback_channels: int
    error: str | None


class SyncTriggerResponse(BaseModel):
    sync_log_id: int
    status: Literal["started"]


class SyncStatusOut(BaseModel):
    last_sync: SyncLogOut | None
    is_running: bool
    next_scheduled_at: datetime | None
    unacknowledged_unsubscribed_count: int
