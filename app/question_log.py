"""Anonymous question log. It powers the data-gap radar: what people ask that NISR's loaded tables cannot answer.

Stores no IP addresses, names or keys: only the question text, language, outcome, tables used and catalogue pointers.
"""
import json
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_lock = threading.Lock()


def log_path():
    return Path(os.getenv("QUESTION_LOG_PATH", ROOT / "data/logs/questions.jsonl"))


def outcome_of(result):
    if result.get("answered_from_data"):
        return "answered" if result["verification"]["status"] == "verified" else "unverified"
    return "gap"


def record(result, mode="ask"):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": (result.get("question") or "")[:300],
        "language": result.get("language", "en"),
        "mode": mode,
        "outcome": outcome_of(result),
        "tables": [c["table_id"] for c in result.get("citations", [])],
        "pointers": [{"title": p["title"], "years": p["years"], "url": p.get("url")} for p in result.get("catalog_pointers", [])],
        "latency_s": result.get("latency_s"),
    }
    path = log_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_entries():
    path = log_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def summary(limit=20):
    """Aggregate view for NISR: how many questions, how many were gaps, which sources people were sent to."""
    entries = read_entries()
    gaps = [e for e in entries if e["outcome"] == "gap"]
    tables = Counter(t for e in entries for t in e["tables"])
    pointers = Counter(p["title"] for e in gaps for p in e["pointers"])
    return {
        "total": len(entries),
        "answered": sum(e["outcome"] == "answered" for e in entries),
        "gaps": len(gaps),
        "unverified": sum(e["outcome"] == "unverified" for e in entries),
        "kinyarwanda": sum(e["language"] == "rw" for e in entries),
        "recent_gaps": [{"question": e["question"], "ts": e["ts"], "pointers": e["pointers"][:3]} for e in reversed(gaps)][:limit],
        "top_tables": tables.most_common(10),
        "top_pointers": pointers.most_common(10),
    }
