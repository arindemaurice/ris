#!/usr/bin/env bash
set -euo pipefail
BACKEND="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BACKEND"
[[ -x .venv/bin/python ]] || { echo 'Run ./install_unix.sh first.' >&2; exit 1; }
[[ -f .env ]] || { echo 'backend/.env missing. Run ./install_unix.sh first.' >&2; exit 1; }
.venv/bin/python worker.py &
WORKER_PID=$!
cleanup() { kill "$WORKER_PID" 2>/dev/null || true; wait "$WORKER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
