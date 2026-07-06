#!/usr/bin/env bash
#
# Options Analysis Dashboard - one-command local launch.
#
# Starts the Python backend, which also serves the built React interface, then
# opens your browser to it. Everything runs on your machine. Nothing is hosted,
# deployed, or uploaded to anyone.
#
# Usage:
#   ./run.sh           start the dashboard (builds the web app on first run)
#   ./run.sh --build   force a fresh rebuild of the web app, then start
#
# Environment overrides (optional):
#   PORT=8010 ./run.sh     serve on a different port
#   NO_OPEN=1 ./run.sh     do not open a browser tab automatically
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
URL="http://localhost:${PORT}"
FORCE_BUILD=0
[ "${1:-}" = "--build" ] && FORCE_BUILD=1

say()  { printf '\033[1;33m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[1;31mwarning: %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31merror: %s\033[0m\n' "$1" >&2; exit 1; }

open_url() {
  [ "${NO_OPEN:-0}" = "1" ] && return 0
  if command -v open >/dev/null 2>&1; then open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1"
  fi
}

command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3 from https://www.python.org/downloads/ then run this again."
command -v npm >/dev/null 2>&1 || die "npm not found. Install Node.js from https://nodejs.org/ then run this again."

# --- Backend: isolated Python environment plus dependencies ---
if [ ! -d .venv ]; then
  say "Creating a local Python environment (.venv), one time only..."
  python3 -m venv .venv
fi
say "Checking backend dependencies..."
./.venv/bin/python -m pip install -q --upgrade pip
./.venv/bin/python -m pip install -q -r requirements.txt

# --- Frontend: install once, build when missing or forced ---
if [ ! -d frontend/node_modules ]; then
  say "Installing web-app dependencies, one time only (this can take a minute)..."
  npm --prefix frontend install
fi
if [ ! -d frontend/dist ] || [ "$FORCE_BUILD" = "1" ]; then
  say "Building the web app..."
  npm --prefix frontend run build
fi

# --- Keys ---
if [ ! -f .env ]; then
  warn "No .env file found. The dashboard will open, but live data needs Alpaca keys."
  printf '  Copy .env.example to .env, add your keys, then restart this script.\n'
fi

# --- Launch ---
say "Starting the dashboard at ${URL}"
say "Keep this window open while you use it. Press Ctrl+C here to stop."
( sleep 2; open_url "$URL" ) &
exec ./.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port "$PORT"
