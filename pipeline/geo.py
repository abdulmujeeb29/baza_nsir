"""Canonical geography for NISR published aggregate tables."""
import csv
import re
import unicodedata
from pipeline.sources import ROOT


# Known spelling slips in the published NISR sheets (documented in the table notes).
ALIASES = {"goma": "ngoma"}


def normalise_name(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    text = re.sub(r"\s+province$", "", text)
    if text in {"kigali", "kigali city", "city of kigali"}:
        return "city of kigali"
    return ALIASES.get(text, text)


with (ROOT / "data/reference/districts.csv").open(encoding="utf-8", newline="") as stream:
    DISTRICTS = list(csv.DictReader(stream))
DISTRICT_BY_NAME = {normalise_name(row["district"]): row for row in DISTRICTS}
PROVINCES = {normalise_name(row["province"]): row["province"] for row in DISTRICTS}


def classify_geo(label):
    name = normalise_name(label)
    if name in DISTRICT_BY_NAME:
        return "district"
    if name in PROVINCES:
        return "province"
    if name in {"rwanda", "all rwanda", "national", "poverty rate", "total", "all"}:
        return "national"
    if name in {"urban", "rural", "urban areas", "rural areas"}:
        return "urban_rural"
    return "other"
