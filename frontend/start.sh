#!/usr/bin/env bash
# Local dev start script: installs dependencies, starts the Vite dev
# server (proxies /api to the backend — see vite.config.ts).
set -euo pipefail
cd "$(dirname "$0")"

echo "Installing frontend dependencies..."
npm install

echo "Starting frontend dev server..."
exec npm run dev
