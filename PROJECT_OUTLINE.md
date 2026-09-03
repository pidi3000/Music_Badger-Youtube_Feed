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
| Sync interval | **Superseded** — env var (`SYNC_INTERVAL_MINUTES`) seeds the initial value only; it and `BACKFILL_WORKER_INTERVAL_SECONDS` are both editable from Settings, live-rescheduling the running APScheduler jobs on change. Requested and built after this outline was written. |
| YouTube API quota strategy | Adaptive: cache responses, fetch uploads incrementally (only new since last sync), back off on quota errors. |
| Deployment topology | Single Docker container — FastAPI serves the built React static files itself. |
| App auth token | Signed httpOnly session cookie set on login with the shared secret. |
| Sync history | A `SyncLog` table ships in v1 (not deferred). |
| Multiple YouTube API keys | Supported — a pool of API keys managed in the SPA Settings UI, stored encrypted in the DB. Used to spread quota for public Data API calls (channel resolution, uploads via API, video details). |
| Key groups | Each key belongs to one of two groups, set per-key in Settings: **background** (scheduled sync, manual "Sync Now", backfill queue) or **active** (interactive, user-initiated single lookups, e.g. resolving a channel when manually adding it). |
| Group isolation | Strict — a group never borrows keys from the other, even if its own group is fully exhausted and the other has spare quota. |
| Manual "Sync Now" pool | Uses the **background** group, same as scheduled sync — it's the same bulk operation, just triggered early. |
| Key rotation (within a group) | Use one key until it's quota-exhausted, then move to the next active key in that group. |
| Upload fetch method | Two methods per channel: **API** (YouTube Data API, full history, richer metadata, uses quota) or **HTTP/RSS** (public `feeds/videos.xml` feed, no key/quota needed, ~15 most recent uploads only, less metadata). Global default + per-channel override. |
| Quota-exhaustion fallback | If a channel is set to `API` but every key in the pool is exhausted, the sync temporarily falls back to `RSS` for that channel and logs/flags that a fallback occurred (surfaced via `SyncLog` / a UI indicator), rather than skipping the channel. |
| Upload caching | All fetched uploads are cached in the DB so they never need to be re-fetched. See §7. |
| Cache pruning | None — once an upload is cached it's kept forever. The 1yr/min-50 rule only governs how far back to *backfill* when a channel is first synced, not later deletion. |
| Retention thresholds | Configurable in Settings (defaults: 1 year back, minimum 50 uploads). |
| RSS backfill | A channel first fetched (or switched) to `rss` gets a one-time `api` backfill to the retention threshold first (if a key is available), then continues on `rss` for ongoing syncs. |
| Backfill execution | Queued, not synchronous — each channel's backfill is a resumable `BackfillTask` (see §7) processed in the background, so a quota outage pauses and resumes it rather than losing progress or blocking anything. |
| Backfill progress UI | The SPA has a dedicated progress view showing every channel's backfill status (queued/in progress/paused/completed), a progress indicator, and why it's paused (e.g. "quota exhausted, resumes ~4h"). |
| Old v2 code | Removed in this branch (`app.py`, `music_feed/`, `migrations/`, `requirements.txt`, `pyproject.toml`, `Dockerfile`) and replaced by the new `backend/` + `frontend/` layout — recoverable from git history / `main` if ever needed. |
| Repo layout | Monorepo: `backend/` (FastAPI app, its own `pyproject.toml`, Alembic migrations, tests) and `frontend/` (Vite + React + TS app, its own `package.json`, tests). Root `Dockerfile` multi-stage builds the frontend then copies its output into the backend image; root `docker-compose.yml` for local dev (app + optional Postgres). |
| Secret encryption | `ApiKey.key_value` and stored YouTube OAuth tokens are encrypted at rest using a symmetric key from an `ENCRYPTION_KEY` env var (required at startup, alongside the existing app-access secret). |
| Build-time YouTube credentials | No real Google OAuth client / API keys are available during this build. The OAuth flow, Data API calls, and RSS parsing are built against mocked/stubbed responses with automated tests; a live end-to-end YouTube login/sync is deferred until real credentials are plugged in later via the Settings UI / env. |
| Delivery | Commits are pushed to this branch incrementally at milestones; no pull request is opened as part of this build. |

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
  `upload_fetch_method` (`api` | `rss`), `backfill_days` (default 365),
  `backfill_min_count` (default 50) — see §7.
- **Channel**
  - `id`, `youtube_channel_id`, `title`, `handle`, `thumbnail_url`
  - `source`: `subscription` | `manual` | `both`
  - `subscription_status`: `subscribed` | `unsubscribed` (see §5)
  - `unsubscribed_at`: nullable timestamp
  - `unsubscribed_ack`: bool — whether the user has dismissed the notification
  - `upload_fetch_method`: nullable `api` | `rss` — per-channel override of
    the global default (see §6)
  - `backfill_completed_at`: nullable timestamp — set once the initial
    history backfill (see §7) has run for this channel
  - `added_at`, `updated_at`
- **Tag** — `id`, `name`, `color`
- **ChannelTag** — many-to-many join table
- **Upload** — `id`, `channel_id`, `youtube_video_id`, `title`, `published_at`,
  `thumbnail_url`, fetched/cached metadata, `fetched_via` (`api` | `rss`, for
  transparency about how each row's data was sourced)
- **ApiKey** — `id`, `label`, `key_value` (encrypted at rest), `group`
  (`background` | `active`), `status` (`active` | `exhausted` |
  `disabled`), `quota_resets_at` (nullable), `last_used_at`, `created_at`
- **BackfillTask** — `id`, `channel_id`, `status` (`queued` |
  `in_progress` | `paused_quota` | `completed` | `failed`),
  `target_min_count`, `target_after` (date cutoff, snapshotted from
  Settings when the task is created so a later Settings change doesn't
  retroactively alter an in-flight task), `fetched_count`, `resume_cursor`
  (opaque pagination token / oldest-fetched timestamp, so work resumes
  exactly where it left off), `attempts`, `last_error`, `created_at`,
  `started_at`, `completed_at`, `updated_at`
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

## 6. Upload fetch methods: API key groups & RSS fallback

Two independent ways to get a channel's uploads:

- **API**: YouTube Data API (`playlistItems`/`search`), using a key from the
  relevant group's pool. Supports full upload history and richer metadata
  (view counts, duration, etc.), but consumes quota.
- **RSS/HTTP**: the public, keyless feed at
  `https://www.youtube.com/feeds/videos.xml?channel_id={id}` (already
  referenced in v2, see `music_feed/db_models/_channel.py`). No quota cost
  and no key required, but only returns the ~15 most recent uploads per
  channel with more limited metadata (no view count/duration).

**Configuration**: `Settings.upload_fetch_method` is the app-wide default;
each `Channel.upload_fetch_method` can override it. The SPA exposes both —
a global setting and a per-channel toggle.

**API key pools — two groups, strictly isolated**:
- Every key (`ApiKey`) is assigned a `group`: **background** or **active**,
  editable per-key in the Settings UI alongside label/status.
- **background** group: used by the scheduled sync, a manually-triggered
  "Sync Now", and all `BackfillTask` processing (§7) — i.e. everything the
  app does on its own initiative or in bulk.
- **active** group: used only by immediate, interactive, single-item calls
  triggered directly by a user action in the SPA — chiefly resolving a
  channel (from video link / ID / handle) during manual channel add. This
  keeps that interaction fast even if a large backfill or sync has burned
  through the entire background pool.
- Within each group: one key is used for all calls until it returns a
  quota-exceeded error, at which point it's marked `exhausted` (with an
  estimated `quota_resets_at`, YouTube quota resets daily at midnight
  Pacific Time) and the next `active`-status key *in the same group* takes
  over.
- **No cross-group borrowing**: if a group's keys are all exhausted, calls
  in that group do not fall back to the other group's keys. Background
  work falls back to RSS (below) or pauses/queues (§7); an active-group
  call (e.g. manual add) simply fails with a clear "quota exhausted, try
  again later or add another active-use key" error — it never silently
  eats into the background pool.
- The Settings UI shows each key's group, status (active/exhausted), and
  reset ETA.
- Note: key pooling only multiplies quota for calls that can run on a
  plain API key (channel resolution, uploads via API, video details).
  Importing the subscription list itself (`subscriptions.list`) requires
  the user's OAuth token and draws from whichever Google Cloud project the
  OAuth client belongs to — no key pool extends that particular quota.

**Exhaustion fallback (ongoing sync, not backfill)**: if a channel is
configured for `api` and every key in the **background** group is
exhausted, the sync job automatically uses `rss` for that channel's
incremental "what's new" fetch for the current cycle instead of skipping
it, and records the fallback on the `SyncLog` entry (and/or a per-channel
"fetched via RSS due to quota" indicator) so it's visible rather than
silent. Once a background key becomes `active` again, subsequent syncs for
that channel go back to `api` (assuming no per-channel override to `rss`).
This fallback does not apply to `BackfillTask` processing — RSS can't
satisfy a backfill target, so a backfill task pauses instead (§7).

## 7. Upload caching, backfill queue & progress UI

Every upload fetched (via API or RSS) is persisted to the `Upload` table
permanently — the feed and channel pages always read from the DB, never
re-fetch from YouTube just to display data. YouTube is only queried by the
sync job to pick up *new* uploads and, via the backfill queue, to fill in
history.

**Backfill target** (per channel): fetch uploads until **both** of the
following are satisfied, whichever requires going further back:
- at least `backfill_min_count` uploads are cached (default: 50), **and**
- all uploads published within the last `backfill_days` are cached
  (default: 365 days).

In other words: go back ~1 year, but if a channel has fewer than 50 uploads
in that window, keep paging further back until 50 are cached (or the
channel's entire history is exhausted, if it has fewer than 50 uploads
ever). Both thresholds are editable in Settings (`backfill_days`,
`backfill_min_count`) and are snapshotted onto each `BackfillTask` when
created.

**Backfill is a queue, not a synchronous step**:
- A `BackfillTask` (queued) is created whenever a channel needs backfilling:
  on first add (subscription import or manual add), or when a channel's
  `upload_fetch_method` is switched to `rss` and it hasn't been backfilled
  yet.
- A background worker (driven by the same in-process scheduler as the sync
  job, ticking independently and more frequently, e.g. every minute) picks
  up `queued`/`paused_quota` tasks and processes them a page at a time
  using a key from the **background** group (§6), persisting
  `resume_cursor` and `fetched_count` after every page — so progress is
  never lost even if the process restarts.
- If every background-group key is exhausted mid-task, the task moves to
  `paused_quota` (keeping its cursor) instead of failing or restarting from
  scratch, and the worker moves on to other tasks / stops for this tick.
  It's automatically retried on a later tick — no manual resume needed —
  and picks up exactly where it left off via `resume_cursor`.
- Once the target is met, the task is marked `completed` and
  `Channel.backfill_completed_at` is set.
- Multiple tasks can be queued at once (e.g. right after importing a large
  subscription list); the worker works through them one at a time (or a
  small number concurrently — an implementation detail, not user-facing).

**Progress UI**: the SPA has a dedicated view (e.g. under Settings or its
own "Sync" page) listing every non-completed `BackfillTask`:
- Per-channel row: channel name/thumbnail, status badge (Queued / In
  progress / Paused — quota exhausted, resumes ~4h / Failed), and a
  progress indicator (`fetched_count` vs `target_min_count`, plus how far
  back it has reached relative to `target_after`).
- A summary banner while any tasks are active, e.g. "Backfilling 12
  channels — 3 in progress, 5 queued, 4 paused (quota exhausted)".
- The SPA polls the relevant endpoint (§8) on an interval while tasks are
  active, rather than a persistent connection — simplest given the
  single-container, no-extra-infra deployment (§2).

**Method used for backfill**:
- `api`-configured channels: the task pages through
  `playlistItems`/`search` directly until the target is met.
- `rss`-configured channels: the RSS feed only returns ~15 items, so it
  can't satisfy the backfill target on its own — these channels' backfill
  tasks always run via the API (background group) regardless of the
  channel's regular fetch method, then the channel switches to `rss` for
  its ongoing incremental syncs once `backfill_completed_at` is set.

**Ongoing syncs** (after backfill completes) only fetch what's new since
`last_synced_at` (via API) or whatever the RSS feed currently returns —
already-cached uploads are never re-fetched. Nothing is ever pruned: once
cached, an upload stays in the DB regardless of how old it gets or how
much the retention thresholds change later.

## 8. API surface (sketch, not final)

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

GET    /api/settings                # incl. upload_fetch_method, backfill_days, backfill_min_count
PATCH  /api/settings

GET    /api/api-keys                # list keys + group + status (active/exhausted, reset ETA)
POST   /api/api-keys                # add a key (incl. group: background|active)
PATCH  /api/api-keys/{id}           # relabel / disable / change group
DELETE /api/api-keys/{id}

GET    /api/backfill-tasks          # list tasks (filterable by status), for the progress UI
POST   /api/backfill-tasks/{id}/retry   # manually re-queue a failed task

POST   /api/sync                    # trigger sync now (background group)
GET    /api/sync/status             # last run, next run, in-progress
```

## 9. Resolved — no open questions remain

All previously open implementation details have been decided (see the table
in §2 for the sync interval, quota strategy, deployment topology, auth
token mechanism, sync logging, API key groups, the API/RSS fetch method,
and the upload caching/backfill queue). Nothing here is blocking
implementation anymore; SyncLog, ApiKey (with `group`), and BackfillTask
are included in the data model (§4) as part of v1.

## 10. Out of scope for this rebuild (unless requested later)

- Multi-user support.
- Data migration from a v2 database — this is a fresh rebuild, not an
  in-place upgrade. (Can be revisited if needed.)

## 11. Tech stack summary

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), Alembic, APScheduler
  (sync schedule + backfill-queue worker tick, both in-process — no
  Celery/Redis), Pydantic v2, `httpx` (RSS fetching + general HTTP) /
  `google-api-python-client` for YouTube Data API calls.
- **Frontend**: React + TypeScript, Vite, a fetch/query layer (e.g.
  TanStack Query) for API calls.
- **DB**: SQLite (dev) / PostgreSQL (prod) via `DATABASE_URL`.
- **Testing**: `pytest` + `httpx` (backend), Vitest + React Testing Library
  (frontend).
- **Deployment**: Docker, single container (FastAPI serves the built SPA).
