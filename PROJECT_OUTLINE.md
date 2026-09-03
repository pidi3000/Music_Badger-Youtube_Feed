# Music Badger — Rebuild Outline

Status: **planning only** — no implementation yet. This document captures the
architecture decisions for the rebuild before any code is written.

## 1. Goals (unchanged from v2)

- Self-hosted, single-user app to browse YouTube uploads with a tag-based
  filtered feed instead of YouTube's native subscription feed.
- New in this rebuild: connect a YouTube account and **auto-import all of its
  subscriptions** as channels, instead of only adding channels manually.

## 2. Decisions made

| Topic | Decision |
|---|---|
| Users | Single-user app (one deployment = one YouTube account). No per-user accounts. |
| App access | Gated by a single shared secret (password / API key) set via env var. No user table, no sessions beyond a simple auth token. |
| Backend framework | FastAPI |
| DB | Flexible via `DATABASE_URL` — SQLite for local/dev, PostgreSQL for production. Both must work unmodified. |
| ORM / DB access | SQLAlchemy 2.0, **async** engine (`asyncpg` for Postgres, `aiosqlite` for SQLite). Alembic for migrations (kept from v2). |
| Frontend | Decoupled SPA: React + TypeScript, calling the FastAPI backend as a pure JSON API (no server-rendered HTML). |
| Manual channel management | Kept alongside auto-sync. You can still add/tag a channel by video link, channel ID, or handle, independent of your subscriptions (same parsing rules as v2, ported forward — see `README.md`). |
| Subscription sync | In-process background scheduler (APScheduler) inside the FastAPI app, running on an interval. No separate worker process/Celery for now. |
| Unsubscribe handling | See §5 — channel is **never auto-deleted**, only flagged and surfaced to the user. |
| Sync interval | Fixed default (e.g. 30 min), overridable via env var at deploy time. No UI setting for it. |
| YouTube API quota strategy | Adaptive: cache responses, fetch uploads incrementally (only new since last sync), back off on quota errors. |
| Deployment topology | Single Docker container — FastAPI serves the built React static files itself. |
| App auth token | Signed httpOnly session cookie set on login with the shared secret. |
| Sync history | A `SyncLog` table ships in v1 (not deferred). |
| Multiple YouTube API keys | Supported — a pool of API keys managed in the SPA Settings UI, stored encrypted in the DB. Used to spread quota for public Data API calls (channel resolution, uploads via API, video details). |
| Key rotation | Use one key until it's quota-exhausted, then move to the next active key in the pool. |
| Upload fetch method | Two methods per channel: **API** (YouTube Data API, full history, richer metadata, uses quota) or **HTTP/RSS** (public `feeds/videos.xml` feed, no key/quota needed, ~15 most recent uploads only, less metadata). Global default + per-channel override. |
| Quota-exhaustion fallback | If a channel is set to `API` but every key in the pool is exhausted, the sync temporarily falls back to `RSS` for that channel and logs/flags that a fallback occurred (surfaced via `SyncLog` / a UI indicator), rather than skipping the channel. |

## 3. High-level architecture

```
┌─────────────────────┐        JSON/HTTPS        ┌──────────────────────────┐
│  React + TS SPA      │ ───────────────────────▶ │  FastAPI backend          │
│  (served as static    │ ◀─────────────────────── │  - REST API                │
│   build, or its own   │                          │  - APScheduler (sync job)  │
│   container)          │                          │  - YouTube OAuth + Data API│
└─────────────────────┘                          └──────────────┬───────────┘
                                                                   │
                                                     SQLAlchemy (async)
                                                                   │
                                                     ┌─────────────▼─────────────┐
                                                     │  SQLite or PostgreSQL      │
                                                     │  (via DATABASE_URL)        │
                                                     └───────────────────────────┘
```

Deployment stays Docker-first: a single container, with FastAPI serving the
built React static files itself.

## 4. Data model (sketch)

- **Settings** — single-row table (or key/value): shared access secret hash,
  YouTube OAuth tokens, sync interval, last sync timestamp, global default
  `upload_fetch_method` (`api` | `rss`).
- **Channel**
  - `id`, `youtube_channel_id`, `title`, `handle`, `thumbnail_url`
  - `source`: `subscription` | `manual` | `both`
  - `subscription_status`: `subscribed` | `unsubscribed` (see §5)
  - `unsubscribed_at`: nullable timestamp
  - `unsubscribed_ack`: bool — whether the user has dismissed the notification
  - `upload_fetch_method`: nullable `api` | `rss` — per-channel override of
    the global default (see §6)
  - `added_at`, `updated_at`
- **Tag** — `id`, `name`, `color`
- **ChannelTag** — many-to-many join table
- **Upload** — `id`, `channel_id`, `youtube_video_id`, `title`, `published_at`,
  `thumbnail_url`, fetched/cached metadata, `fetched_via` (`api` | `rss`, for
  transparency about how each row's data was sourced)
- **ApiKey** — `id`, `label`, `key_value` (encrypted at rest), `status`
  (`active` | `exhausted` | `disabled`), `quota_resets_at` (nullable),
  `last_used_at`, `created_at`
- **SyncLog** — `id`, `started_at`, `finished_at`, `status`,
  `channels_added`, `channels_marked_unsubscribed`, `rss_fallback_channels`
  (list/count of channels that fell back to RSS due to key exhaustion),
  `error`

This is intentionally close to v2's schema (`_channel.py`, `_tag.py`,
`_channel_tag.py`, `_upload.py`, `_yt_credentials.py`) plus the new
subscription-tracking and API-key/fetch-method fields.

## 5. Unsubscribe handling (core new requirement)

On every sync:

1. Fetch the current list of subscriptions from the YouTube Data API
   (`subscriptions.list`, `mine=true`).
2. Any locally stored channel with `source` including `subscription` that is
   **no longer** in that list gets:
   - `subscription_status = unsubscribed`
   - `unsubscribed_at = now()`
   - `unsubscribed_ack = false`
   - Its tags, uploads, and history are **kept**, not deleted.
3. Any subscription present on YouTube but not yet stored locally gets
   created as a new `Channel` (`source = subscription`).
4. If a channel was previously marked `unsubscribed` and reappears in the
   subscriptions list (re-subscribed), it flips back to `subscribed` and
   clears `unsubscribed_at`/`unsubscribed_ack`.

The user is informed via:
- A notification/badge count in the SPA (e.g. "2 channels you unsubscribed
  from on YouTube") backed by `subscription_status = unsubscribed AND
  unsubscribed_ack = false`.
- The channel still appears in lists/feed (unless filtered out) with a
  visible "unsubscribed on YouTube" indicator.
- An endpoint to acknowledge/dismiss the notification per channel (sets
  `unsubscribed_ack = true`) without deleting anything.
- Manually-added channels (`source = manual`, not from subscriptions) are
  unaffected by this logic entirely.

## 6. Upload fetch methods: API key pool & RSS fallback

Two independent ways to get a channel's uploads:

- **API**: YouTube Data API (`playlistItems`/`search`), using a key from the
  API-key pool. Supports full upload history and richer metadata (view
  counts, duration, etc.), but consumes quota.
- **RSS/HTTP**: the public, keyless feed at
  `https://www.youtube.com/feeds/videos.xml?channel_id={id}` (already
  referenced in v2, see `music_feed/db_models/_channel.py`). No quota cost
  and no key required, but only returns the ~15 most recent uploads per
  channel with more limited metadata (no view count/duration).

**Configuration**: `Settings.upload_fetch_method` is the app-wide default;
each `Channel.upload_fetch_method` can override it. The SPA exposes both —
a global setting and a per-channel toggle.

**API key pool**:
- Multiple keys can be added, labeled, and removed from the SPA Settings
  UI; stored encrypted in the DB (`ApiKey`).
- One key is used for all API calls until it returns a quota-exceeded
  error, at which point it's marked `exhausted` (with an estimated
  `quota_resets_at`, YouTube quota resets daily at midnight Pacific Time)
  and the next `active` key in the pool takes over.
- The Settings UI shows each key's status (active/exhausted) and reset
  ETA.
- Note: this pooling only multiplies quota for calls that can run on a
  plain API key (channel resolution, uploads via API, video details).
  Importing the subscription list itself (`subscriptions.list`) requires
  the user's OAuth token and draws from whichever Google Cloud project the
  OAuth client belongs to — the key pool does not extend that particular
  quota.

**Exhaustion fallback**: if a channel is configured for `api` and every key
in the pool is `exhausted`, the sync job automatically uses `rss` for that
channel for the current cycle instead of skipping it, and records the
fallback on the `SyncLog` entry (and/or a per-channel "fetched via RSS due
to quota" indicator) so it's visible rather than silent. Once a key becomes
`active` again, subsequent syncs for that channel go back to `api`
(assuming no per-channel override to `rss`).

## 7. API surface (sketch, not final)

```
POST   /api/auth/login              # shared secret -> app session/token
GET    /api/auth/youtube/start      # begin YouTube OAuth flow
GET    /api/auth/youtube/callback
DELETE /api/auth/youtube            # disconnect YouTube account

GET    /api/channels                # list, filterable by tag / status
POST   /api/channels                # manual add (video link / ID / handle)
GET    /api/channels/{id}
PATCH  /api/channels/{id}           # e.g. tag assignment, fetch method override
DELETE /api/channels/{id}           # manual removal (user-initiated only)
POST   /api/channels/{id}/ack-unsubscribe

GET    /api/tags
POST   /api/tags
PATCH  /api/tags/{id}
DELETE /api/tags/{id}

GET    /api/feed                    # uploads, filterable by tag(s)

GET    /api/settings                # incl. global upload_fetch_method
PATCH  /api/settings

GET    /api/api-keys                # list keys + status (active/exhausted, reset ETA)
POST   /api/api-keys                # add a key
PATCH  /api/api-keys/{id}           # relabel / disable
DELETE /api/api-keys/{id}

POST   /api/sync                    # trigger sync now
GET    /api/sync/status             # last run, next run, in-progress
```

## 8. Resolved — no open questions remain

All previously open implementation details have been decided (see the table
in §2 for the sync interval, quota strategy, deployment topology, auth
token mechanism, sync logging, API key pooling, and the API/RSS fetch
method). Nothing here is blocking implementation anymore; SyncLog and
ApiKey are included in the data model (§4) as part of v1.

## 9. Out of scope for this rebuild (unless requested later)

- Multi-user support.
- Data migration from a v2 database — this is a fresh rebuild, not an
  in-place upgrade. (Can be revisited if needed.)

## 10. Tech stack summary

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), Alembic, APScheduler,
  Pydantic v2, `httpx` (RSS fetching + general HTTP) /
  `google-api-python-client` for YouTube Data API calls.
- **Frontend**: React + TypeScript, Vite, a fetch/query layer (e.g.
  TanStack Query) for API calls.
- **DB**: SQLite (dev) / PostgreSQL (prod) via `DATABASE_URL`.
- **Testing**: `pytest` + `httpx` (backend), Vitest + React Testing Library
  (frontend).
- **Deployment**: Docker, single container (FastAPI serves the built SPA).
