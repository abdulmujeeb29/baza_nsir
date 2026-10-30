import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_live_url():
    live = os.getenv("LIVE_URL", "").strip()
    assert re.search(r"\*\*Live demo:\*\*\s*\S+", README)
    if live:
        assert live in README


def test_required_sections():
    for needle in ["Track 3", "NST2", "Vision 2050", "Carlos Ngoga", "Abdulmujeeb Tiamiyu", "Limitations"]:
        assert needle in README, needle
    assert re.search(r"ai use disclosure", README, re.I)
    assert README.count("statistics.gov.rw") >= 5
    assert re.search(r"!\[[^\]]*\]\([^)]+\.(png|gif|jpg)\)", README)
    assert "```mermaid" in README
    assert "CC BY 4.0" in README


def test_no_em_dash_in_docs():
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        assert "—" not in path.read_text(encoding="utf-8"), path.name


def test_image_links_exist():
    for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", README):
        if not target.startswith("http"):
            assert (ROOT / target).exists(), target


def test_evaluation_table_present():
    block = README.split("<!-- EVAL:START -->")[1].split("<!-- EVAL:END -->")[0]
    assert "Score:" in block and block.count("\n| ") >= 12
