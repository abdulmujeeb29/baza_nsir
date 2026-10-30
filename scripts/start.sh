#!/usr/bin/env bash
# Start Baza NISR. No Docker: the host installs requirements.txt, then runs this script.
set -e
cd "$(dirname "$0")/.."
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
[ -f data/baza.duckdb ] || "$PY" pipeline/build_db.py
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
