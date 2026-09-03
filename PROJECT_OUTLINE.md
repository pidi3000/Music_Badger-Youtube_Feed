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

Deployment stays Docker-first. Whether the SPA is served by the FastAPI
process (mounted static files) or as a separate container behind a reverse
proxy is an open implementation detail (§7), not a blocker.

## 4. Data model (sketch)

- **Settings** — single-row table (or key/value): shared access secret hash,
  YouTube OAuth tokens, sync interval, last sync timestamp.
- **Channel**
  - `id`, `youtube_channel_id`, `title`, `handle`, `thumbnail_url`
  - `source`: `subscription` | `manual` | `both`
  - `subscription_status`: `subscribed` | `unsubscribed` (see §5)
  - `unsubscribed_at`: nullable timestamp
  - `unsubscribed_ack`: bool — whether the user has dismissed the notification
  - `added_at`, `updated_at`
- **Tag** — `id`, `name`, `color`
- **ChannelTag** — many-to-many join table
- **Upload** — `id`, `channel_id`, `youtube_video_id`, `title`, `published_at`,
  `thumbnail_url`, fetched/cached metadata
- **SyncLog** (optional but useful) — `id`, `started_at`, `finished_at`,
  `status`, `channels_added`, `channels_marked_unsubscribed`, `error`

This is intentionally close to v2's schema (`_channel.py`, `_tag.py`,
`_channel_tag.py`, `_upload.py`, `_yt_credentials.py`) plus the new
subscription-tracking fields.

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

## 6. API surface (sketch, not final)

```
POST   /api/auth/login              # shared secret -> app session/token
GET    /api/auth/youtube/start      # begin YouTube OAuth flow
GET    /api/auth/youtube/callback
DELETE /api/auth/youtube            # disconnect YouTube account

GET    /api/channels                # list, filterable by tag / status
POST   /api/channels                # manual add (video link / ID / handle)
GET    /api/channels/{id}
PATCH  /api/channels/{id}           # e.g. tag assignment
DELETE /api/channels/{id}           # manual removal (user-initiated only)
POST   /api/channels/{id}/ack-unsubscribe

GET    /api/tags
POST   /api/tags
PATCH  /api/tags/{id}
DELETE /api/tags/{id}

GET    /api/feed                    # uploads, filterable by tag(s)

POST   /api/sync                    # trigger sync now
GET    /api/sync/status             # last run, next run, in-progress
```

## 7. Open implementation details (to resolve during build, non-blocking)

These don't need to be decided before coding starts, but are flagged so
they're not forgotten:

- Exact sync interval and whether it's user-configurable from the UI.
- YouTube Data API quota strategy (subscriptions can be large; uploads need
  per-channel `playlistItems`/`search` calls — batching/backoff approach).
- Whether the SPA is built and served as static files by FastAPI in one
  Docker image (closer to v2's single-container deployment) or split into
  two containers behind a reverse proxy.
- Session/token mechanism for the shared-secret login (simple signed cookie
  vs bearer token stored client-side).
- Whether `SyncLog` ships in v1 of the rebuild or is added later.

## 8. Out of scope for this rebuild (unless requested later)

- Multi-user support.
- Data migration from a v2 database — this is a fresh rebuild, not an
  in-place upgrade. (Can be revisited if needed.)

## 9. Tech stack summary

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), Alembic, APScheduler,
  Pydantic v2, `httpx`/`google-api-python-client` for YouTube API calls.
- **Frontend**: React + TypeScript, Vite, a fetch/query layer (e.g.
  TanStack Query) for API calls.
- **DB**: SQLite (dev) / PostgreSQL (prod) via `DATABASE_URL`.
- **Testing**: `pytest` + `httpx` (backend), Vitest + React Testing Library
  (frontend).
- **Deployment**: Docker (details per §7).
