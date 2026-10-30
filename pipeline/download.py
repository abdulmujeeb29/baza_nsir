"""Fetch missing workbooks, preserve original bytes, and record provenance."""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from openpyxl import load_workbook
from pipeline.sources import ROOT, SOURCES


def download_all():
    directory = ROOT / "data/raw"
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "SOURCES.json"
    previous = {}
    if manifest_path.exists():
        previous = {entry["key"]: entry for entry in json.loads(manifest_path.read_text())}
    entries = []
    for source in SOURCES:
        target = directory / source["filename"]
        fetched = not target.exists()
        if fetched:
            for attempt in range(3):
                try:
                    response = httpx.get(source["url"], follow_redirects=True, timeout=60)
                    response.raise_for_status()
                    temporary = target.with_suffix(".xlsx.part")
                    temporary.write_bytes(response.content)
                    with temporary.open("rb") as stream:
                        workbook = load_workbook(stream, read_only=True)
                        workbook.close()
                    temporary.replace(target)
                    break
                except (httpx.HTTPError, OSError, ValueError) as error:
                    if attempt == 2:
                        raise RuntimeError(f"Cannot download {source['filename']}. Put the official workbook in data/raw/ and retry.") from error
                    time.sleep(attempt + 1)
        workbook = load_workbook(target, read_only=True)
        workbook.close()
        entries.append({"key": source["key"], "url": source["url"], "filename": source["filename"], "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "downloaded_at": previous.get(source["key"], {}).get("downloaded_at", datetime.now(timezone.utc).isoformat()), "origin": previous.get(source["key"], {}).get("origin", "downloaded from statistics.gov.rw by pipeline/download.py" if fetched else "existing local file")})
        manifest_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
        print(f"Ready: {source['filename']}")
    return entries


if __name__ == "__main__":
    try:
        download_all()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
