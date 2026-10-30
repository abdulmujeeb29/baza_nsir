"""Parse every registered NISR table and build data/baza.duckdb plus data/clean/*.csv."""
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import pandas as pd

from pipeline.geo import DISTRICTS
from pipeline.parse_excel import parse_lfs_sheet, parse_sheet
from pipeline.sources import ROOT, SOURCE_BY_KEY
from pipeline.tables import TABLES

DB_PATH = ROOT / "data/baza.duckdb"
CLEAN = ROOT / "data/clean"
GEO_COLUMNS = ["label", "breakdown", "geo_level", "province", "district", "area"]
STAT_COLUMNS = {"std_error", "ci_low", "ci_high", "cv", "design_effect", "unweighted_count"}
COLUMN_MEANINGS = {
    "label": "row label exactly as written by NISR",
    "breakdown": "section the row belongs to (for example District, Province, Quintile, Sex)",
    "geo_level": "national, province, district, urban_rural or other",
    "province": "province name (City of Kigali, Southern, Western, Northern, Eastern)",
    "district": "district name, one of the 30 districts (NULL when the row is not a district)",
    "area": "total, urban or rural",
    "value": "the estimate",
    "std_error": "standard error of the estimate",
    "ci_low": "lower bound of the 95% confidence interval",
    "ci_high": "upper bound of the 95% confidence interval",
    "cv": "coefficient of variation (%)",
    "design_effect": "survey design effect",
    "unweighted_count": "number of sampled households",
    "households_thousands": "total number of households, in thousands",
    "indicator": "indicator name as written by NISR",
    "group": "population group (Total, Male, Female, Urban, Rural, Youth, Adult)",
    "year": "survey year",
    "quarter": "quarter (Q1 to Q4)",
    "period": "year and quarter, for example 2026Q2",
}


def parse_table(entry):
    path = ROOT / "data/raw" / SOURCE_BY_KEY[entry["source_key"]]["filename"]
    if entry.get("parser") == "lfs":
        return parse_lfs_sheet(path, entry["sheet"])
    return parse_sheet(path, entry["sheet"], entry.get("first_col_name"),
                       entry.get("short_names", False), entry.get("rename"))


def sex_of(column):
    if re.search(r"(^|_)female", column):
        return "female"
    if re.search(r"(^|_)male", column):
        return "male"
    return "both"


def long_rows(entry, frame):
    if entry.get("parser") == "lfs":
        latest = frame[frame["period"] == frame["period"].max()]
        out = latest.assign(indicator=latest["indicator"] + " (" + latest["group"] + ", " + latest["period"] + ")",
                            sex=latest["group"].str.casefold().map({"male": "male", "female": "female"}).fillna("both"))
        out = out.drop(columns=["group", "year", "quarter", "period"]).assign(label=None, breakdown=None)
    else:
        value_cols = [c for c in frame.columns if c not in GEO_COLUMNS and c not in STAT_COLUMNS]
        out = frame.melt(id_vars=GEO_COLUMNS, value_vars=value_cols, var_name="indicator", value_name="_value")
        out = out.dropna(subset=["_value"]).rename(columns={"_value": "value"})
        out["sex"] = out["indicator"].map(sex_of)
    out["table_id"] = entry["table_id"]
    out["unit"] = entry["unit"]
    return out[["table_id", "indicator", "geo_level", "province", "district", "area", "sex", "value", "unit", "label", "breakdown"]]


def describe_columns(frame):
    parts = []
    for column in frame.columns:
        meaning = COLUMN_MEANINGS.get(column, "numeric value from the NISR table")
        parts.append(f"{column}: {meaning}")
    return "; ".join(parts)


def build():
    CLEAN.mkdir(parents=True, exist_ok=True)
    report, catalog, longs, frames = {}, [], [], {}
    for entry in TABLES:
        title, frame = parse_table(entry)
        frames[entry["table_id"]] = frame
        frame.to_csv(CLEAN / f"{entry['table_id']}.csv", index=False)
        numeric = [c for c in frame.columns if c not in GEO_COLUMNS and pd.api.types.is_numeric_dtype(frame[c])]
        districts = frame.loc[frame["geo_level"] == "district", "district"]
        warnings = []
        if "district" in entry["geography_levels"] and districts.nunique() != 30:
            warnings.append(f"expected 30 districts, found {districts.nunique()}")
        report[entry["table_id"]] = {"title": title, "rows": len(frame), "district_rows": int(len(districts)),
                                     "unique_districts": int(districts.nunique()), "numeric_cols": numeric,
                                     "warnings": warnings}
        source = SOURCE_BY_KEY[entry["source_key"]]
        catalog.append({
            "table_id": entry["table_id"], "source_key": entry["source_key"], "survey": source["survey"],
            "year": source["year"], "nisr_table_ref": entry["nisr_table_ref"], "title": title,
            "indicator_name": entry["indicator_name"], "unit": entry["unit"],
            "geography_levels": entry["geography_levels"], "columns_description": describe_columns(frame),
            "source_file_url": source["url"], "report_page_url": source["report_page_url"],
            "notes": entry["notes"], "row_count": len(frame),
        })
        longs.append(long_rows(entry, frame))
    (CLEAN / "_parse_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    catalog_frame = pd.DataFrame(catalog)
    long_frame = pd.concat(longs, ignore_index=True)
    districts_frame = pd.DataFrame(DISTRICTS)
    districts_frame["district_code"] = districts_frame["district_code"].astype(int)
    catalog_frame.to_csv(CLEAN / "_catalog.csv", index=False)

    temporary = DB_PATH.with_suffix(".duckdb.tmp")
    temporary.unlink(missing_ok=True)
    con = duckdb.connect(str(temporary))
    for name, frame in {"districts": districts_frame, "catalog": catalog_frame, "indicators_long": long_frame, **frames}.items():
        con.register("frame", frame)
        con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM frame')
        con.unregister("frame")
    con.close()
    temporary.replace(DB_PATH)
    write_data_dictionary(catalog_frame)
    print(f"Built {DB_PATH.relative_to(ROOT)}: {len(catalog)} tables, {len(long_frame)} indicator rows")
    return report


def write_data_dictionary(catalog_frame):
    lines = ["# Data dictionary", "",
             "Generated from the `catalog` table by `pipeline/build_db.py`. All data: National Institute of Statistics of Rwanda (NISR), CC BY 4.0.", "",
             "Every table also has the columns `label`, `breakdown`, `geo_level`, `province`, `district` and `area` (LFS tables: `geo_level`, `province`, `district`, `area`, then the long format columns).", ""]
    for row in catalog_frame.itertuples():
        lines += [f"## `{row.table_id}`", "",
                  f"- Title: {row.title}",
                  f"- Survey: {row.survey}, {row.year}",
                  f"- NISR reference: {row.nisr_table_ref}",
                  f"- Unit: {row.unit}",
                  f"- Geography: {row.geography_levels}",
                  f"- Notes: {row.notes}",
                  f"- Source file: {row.source_file_url}",
                  f"- Report page: {row.report_page_url}",
                  "- Columns:"]
        lines += [f"  - {part}" for part in row.columns_description.split("; ")]
        lines.append("")
    (ROOT / "docs/data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    build()
