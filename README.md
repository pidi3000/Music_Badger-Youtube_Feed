# Music Badger

A self-hosted, tag-based YouTube upload feed. Connect your YouTube account
to auto-import your subscriptions, tag channels however you like, and
browse a feed filtered by tag instead of YouTube's native, unsorted
subscription feed. Channels can also be added manually (by video link,
channel ID, or handle) independent of your subscriptions.

Full design rationale and decisions live in [PROJECT_OUTLINE.md](PROJECT_OUTLINE.md).

## Features

- **Auto-synced subscriptions** — connect your YouTube account and every
  subscription is imported as a channel automatically. If you unsubscribe
  from a channel on YouTube, it's never deleted here — it's flagged so you
  can see it and dismiss the notice yourself.
- **Manual channel add** — add any channel by pasting a video link, channel
  ID, or handle, and tag it, independent of your subscriptions.
- **Tag-based filtering** — organize channels with tags and filter the feed
  by tag.
- **Two ways to fetch uploads, per channel or globally** — the YouTube Data
  API (full history, richer metadata, uses quota) or the public, keyless
  RSS feed (no quota, but only the ~15 most recent uploads).
- **Multiple API keys, in two groups** — pool as many YouTube Data API keys
  as you want, split into a **background** group (scheduled sync, manual
  "Sync Now", backfill) and an **active** group (interactive actions like
  resolving a channel you're adding), so a busy background sync never
  starves the UI of quota.
- **Resumable backfill queue** — new channels get their upload history
  backfilled (configurable: at least N uploads, going back M days,
  whichever needs more paging) via a queue that survives quota exhaustion —
  it pauses and resumes automatically rather than losing progress. A
  dedicated page shows live progress per channel.
- **Uploads are cached forever** — once fetched, an upload is never
  re-fetched or deleted.
- **DB-flexible** — SQLite or PostgreSQL, picked via `DATABASE_URL`.

## Quick start (Docker Compose)

```bash
cp .env.example .env
# edit .env: set APP_ACCESS_SECRET, ENCRYPTION_KEY (see comment in the file
# for how to generate one), and SESSION_SECRET at minimum.

docker compose up --build
```

The app is served at `http://localhost:8000`. `docker-compose.yml` runs
PostgreSQL alongside it by default; to use SQLite instead, drop the `db`
service and the `DATABASE_URL` override in `docker-compose.yml` (the
image's built-in default is a SQLite file under the `app-data` volume).

A single-container `docker build -t music-badger .` (from the repo root)
also works standalone — see the root `Dockerfile`. It runs
`alembic upgrade head` on startup before serving.

> **Note:** the Docker build has been reviewed but not executed in this
> environment (no Docker daemon was available in the sandbox this was
> built in) — build and run it yourself before relying on it, and open an
> issue if something doesn't come up cleanly.

### Connecting YouTube

Subscription auto-import needs a Google Cloud OAuth client with the
YouTube Data API v3 enabled: set `YOUTUBE_OAUTH_CLIENT_ID`,
`YOUTUBE_OAUTH_CLIENT_SECRET`, and `YOUTUBE_OAUTH_REDIRECT_URI` (must match
an authorized redirect URI on the OAuth client) in `.env`, then use
"Connect YouTube" in Settings. Without it, the app still works for manual
channel add/tagging — you'll just need at least one Data API key added in
Settings (for manual-add channel resolution and any `api`-mode fetching).

## Configuration

All settings are environment variables read by the backend
(`backend/app/config.py`); see `.env.example` for the full list with
comments. The key ones:

| Variable | Purpose |
|---|---|
| `APP_ACCESS_SECRET` | The one password gating the app (single-user, no accounts). |
| `ENCRYPTION_KEY` | Fernet key encrypting stored API keys / YouTube tokens at rest. |
| `SESSION_SECRET` | Signs the login session cookie. |
| `DATABASE_URL` | SQLAlchemy async URL — `sqlite+aiosqlite:///...` or `postgresql+asyncpg://...`. |
| `SYNC_INTERVAL_MINUTES` | How often the background sync runs (default 30). |
| `YOUTUBE_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Google OAuth client for subscription import. |

Everything else (upload fetch method, backfill retention thresholds, API
keys and their groups) is configured at runtime from the Settings page,
not env vars.

## Development

Backend (FastAPI, Python 3.11+):

```bash
cd backend
uv venv .venv && uv pip install -e ".[dev]"   # or: python -m venv .venv && pip install -e ".[dev]"
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload
pytest                                         # 50 tests, mocked YouTube — see below
```

Frontend (React + TypeScript, Vite):

```bash
cd frontend
npm install
npm run dev        # proxies /api to http://localhost:8000, see vite.config.ts
npm run build       # typecheck + production build
```

### Testing notes

No real Google OAuth client or YouTube Data API key was available while
building this, so the YouTube integration (OAuth flow, Data API calls, RSS
parsing) is exercised entirely through automated tests against mocked
responses (`backend/tests/`) rather than a live account — 50 tests cover
the channel-link parser, API key rotation/exhaustion, RSS feed parsing,
the backfill queue's pause/resume behavior, subscription/unsubscribe
sync logic, and the REST API end to end. A live end-to-end YouTube login
and sync should be verified once real credentials are configured.

## Manual channel add — link parsing rules

A new channel can be added using a video from the channel, the channel ID,
or the channel handle. Regardless of the rules below, if the `Channel
Link` field contains the domain `youtube.com` or `youtu.be`, it and
everything before it is stripped first.

**From video** — the (post-strip) field must be a URL with the path
`watch?`, with a `v=video_id` parameter at any position (other params like
`si=xyz` are fine alongside it).

**From ID** — either a URL with the path `channel/` followed by the
channel ID, or just the channel ID on its own, which **must** start with
`UC`.

**From handle** — just the channel handle (a leading `@` is recommended
but optional), more than 3 characters (excluding `@`), containing only
`A–Z a–z 0–9 _ - .`.

Examples:

| Input | Good? | Interpreted as |
|---|---|---|
| `youtube.com/watch?v=VIDEO_ID` | ✅ | video |
| `watch?si=xyz&v=VIDEO_ID` | ✅ | video |
| `channel/CHANNEL_ID` | ✅ | channel ID |
| `UCabc` | ✅ | channel ID (must start with `UC`) |
| `https://youtu.be/CHANNEL_HANDLE` | ✅ | handle |
| `youtube.com/@CHANNEL_HANDLE` | ✅ | handle |
| `@CHANNEL_HANDLE` | ✅ | handle |
| `CHANNEL_HANDLE` | ✅ | handle |
| `CHANNEL_ID` (no `UC` prefix) | ⚠️ | interpreted as a handle, not an ID |
| `@ab` | ❌ | too short |
| `@abcd!` | ❌ | disallowed character |
| `v=VIDEO_ID` | ❌ | missing the `watch?` path |

## Project layout

```
backend/     FastAPI app (async SQLAlchemy, Alembic, APScheduler)
  app/
    models.py, schemas.py        ORM models / API contract
    services/                    channel parsing, YouTube client, OAuth,
                                  RSS, key pool, sync, backfill queue
    api/                         REST routers
  migrations/                    Alembic
  tests/                         pytest, mocked YouTube

frontend/    React + TypeScript SPA (Vite, TanStack Query, react-router)
  src/
    api/          typed API client per resource
    pages/         Feed, Channels, Tags, Settings, Backfill progress, Login
    components/

Dockerfile             multi-stage: builds the SPA, bakes it into the API image
docker-compose.yml      app + PostgreSQL for local/prod use
```
