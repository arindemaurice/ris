#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || python3 setup.py
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python worker.py &
WORKER_PID=$!
cleanup() { kill "$WORKER_PID" 2>/dev/null || true; wait "$WORKER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
python -m uvicorn app:app --host 127.0.0.1 --port 8000
