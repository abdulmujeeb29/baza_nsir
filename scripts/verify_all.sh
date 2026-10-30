#!/usr/bin/env bash
# Final gate for Baza NISR. Runs every local gate and fails fast.
# Live checks run only when LIVE_URL (e.g. https://baza.example.org) and GITHUB_REPO (owner/name) are set.
# Set EVAL_MODE=cached to reuse docs/evaluation.json instead of calling the LLM again.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python

gate() { echo; echo "==> GATE: $1"; }

gate "unit and integration tests"
"$PY" -m pytest -q

gate "data build and freshness"
"$PY" pipeline/download.py >/dev/null
"$PY" pipeline/build_db.py
"$PY" - <<'PY'
import duckdb, json
con = duckdb.connect("data/baza.duckdb", read_only=True)
count = con.execute("SELECT count(*) FROM catalog").fetchone()[0]
missing = con.execute("SELECT count(*) FROM catalog WHERE source_file_url IS NULL").fetchone()[0]
assert count >= 20 and missing == 0, (count, missing)
report = json.load(open("data/clean/_parse_report.json"))
bad = {k: v["warnings"] for k, v in report.items() if v["warnings"]}
assert not bad, bad
print(f"catalog has {count} tables, all with source URLs, no parse warnings")
PY

gate "evaluation (12 questions, need >= 10 and zero unverified)"
HAS_KEY=$("$PY" -c "from app.llm import config; print('yes' if config()['api_key'] else 'no')")
if [ "${EVAL_MODE:-live}" != "cached" ] && [ "$HAS_KEY" = "yes" ]; then
  "$PY" scripts/run_eval.py
else
  echo "Using the last saved evaluation (docs/evaluation.json)."
  "$PY" - <<'PY'
import json
data = json.load(open("docs/evaluation.json"))
unverified = sum(r["verifier"] == "unverified" for r in data["rows"])
print(f"saved score {data['score']}/{data['total']}, unverified {unverified}")
assert data["total"] == 12 and data["score"] >= 10 and unverified == 0
PY
fi

gate "README checks"
"$PY" -m pytest -q tests/test_readme.py

gate "secret scan"
grep -qx ".env" .gitignore || { echo ".env is not in .gitignore"; exit 1; }
"$PY" - <<'PY'
import os, re
from pathlib import Path
from dotenv import dotenv_values
secrets = [v for k, v in dotenv_values(".env").items() if v and ("KEY" in k or "SECRET" in k or "TOKEN" in k) and len(v) >= 8] if Path(".env").exists() else []
patterns = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|(?:ANTHROPIC|OPENAI|GEMINI|LLM)_API_KEY=[A-Za-z0-9_-]{24,})")
skip_dirs = {".venv", ".git", "__pycache__", ".pytest_cache", "node_modules"}
hits = []
for path in Path(".").rglob("*"):
    if not path.is_file() or skip_dirs & set(path.parts) or path.name == ".env" or path.stat().st_size > 20_000_000:
        continue
    try:
        data = path.read_bytes()
    except OSError:
        continue
    for secret in secrets:
        if secret.encode() in data:
            hits.append(f"{path}: contains a value from .env")
    if path.suffix not in {".xlsx", ".duckdb", ".png"}:
        text = data.decode("utf-8", "ignore")
        for match in patterns.finditer(text):
            if path.name != ".env.example":
                hits.append(f"{path}: looks like a key ({match.group(0)[:6]}...)")
if hits:
    print("\n".join(hits))
    raise SystemExit(1)
print("no secrets found outside .env; .env is git-ignored")
PY

gate "no Docker"
test ! -f Dockerfile && echo "no Dockerfile"

if [ -n "${LIVE_URL:-}" ]; then
  gate "live app at $LIVE_URL"
  curl -fsS "$LIVE_URL/api/health" | grep -q '"status":"ok"'
  curl -fsS -X POST "$LIVE_URL/api/ask" -H 'content-type: application/json' \
    -d '{"question":"Which district has the highest poverty rate?"}' | grep -q "Nyamagabe"
  echo "live health and Nyamagabe check passed"
  LIVE_URL="$LIVE_URL" "$PY" -m pytest -q tests/test_readme.py::test_live_url
else
  echo; echo "NOTE: LIVE_URL not set, live app checks skipped."
fi

if [ -n "${GITHUB_REPO:-}" ]; then
  gate "public GitHub repo $GITHUB_REPO"
  curl -fsS "https://api.github.com/repos/$GITHUB_REPO" | grep -q '"private": false'
  echo "repository is public"
else
  echo "NOTE: GITHUB_REPO not set, public repo check skipped."
fi

echo
echo "ALL GATES PASSED"
