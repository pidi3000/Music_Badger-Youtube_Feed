#!/usr/bin/env bash
# Local dev start script: loads env vars, runs migrations, starts the API
# server with autoreload. See README.md "Development" for the manual steps
# this wraps.
set -euo pipefail
cd "$(dirname "$0")"

# Load environment variables from .env — repo root (where .env.example
# lives and docker-compose expects it) if present, else backend/.env.
if [ -f ../.env ]; then
  set -a
  source ../.env
  set +a
elif [ -f .env ]; then
  set -a
  source .env
  set +a
else
  echo "No .env file found (expected at repo root or backend/.env)." >&2
  echo "Copy .env.example to .env and fill it in first." >&2
fi

if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

echo "Running database migrations..."
alembic upgrade head

echo "Starting backend server on http://localhost:8000 ..."
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
