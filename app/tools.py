"""Agent tools: search_catalog, describe_table, run_sql, make_chart."""
import math
import re
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from rapidfuzz import fuzz, process

from app.sql_guard import MAX_ROWS, check_sql

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/baza.duckdb"
TIMEOUT_SECONDS = 5

SYNONYMS = {
    "poverty": ["poor", "headcount", "poverty"],
    "poor": ["poverty", "headcount"],
    "electricity": ["lighting", "power", "electricity", "reg"],
    "power": ["electricity", "lighting"],
    "lighting": ["electricity", "lighting"],
    "internet": ["online", "internet", "connectivity"],
    "online": ["internet"],
    "insurance": ["mutuelle", "health insurance", "medical insurance", "insurance"],
    "mutuelle": ["insurance", "health insurance"],
    "health": ["insurance", "medical"],
    "water": ["drinking water", "water"],
    "population": ["people", "residents", "population"],
    "people": ["population", "residents"],
    "density": ["population density", "density"],
    "unemployment": ["unemployment", "labour", "jobs", "lu1"],
    "jobs": ["employment", "unemployment", "labour"],
    "employment": ["employment", "workforce", "labour"],
    "work": ["workforce", "employment", "labour"],
    "phone": ["mobile phone", "smartphone", "phone"],
    "smartphone": ["smartphone", "smart phone"],
    "toilet": ["sanitation", "latrine"],
    "sanitation": ["sanitation", "toilets"],
    "cooking": ["cooking", "fuel", "firewood", "charcoal"],
    "fuel": ["cooking fuel", "firewood", "charcoal"],
    "youth": ["youth", "young"],
    "young": ["youth"],
    "farming": ["agricultural", "agriculture"],
    "agriculture": ["agricultural", "farming"],
    "women": ["female", "headed by women"],
    "female": ["women", "female"],
    "disability": ["disability", "disabilities"],
    "birth": ["birth registration"],
    "road": ["all-weather road", "road"],
    "transport": ["public transport", "bus"],
    "household": ["household size", "households"],
}
STOPWORDS = {"the", "a", "an", "of", "in", "by", "and", "or", "for", "to", "what", "which", "is", "are", "how",
             "with", "has", "have", "show", "me", "rate", "rates", "share", "percentage", "level", "levels",
             "per", "do", "does", "most", "highest", "lowest", "top", "compare", "across", "between", "than",
             "district", "districts", "province", "provinces", "rwanda", "national", "average", "data", "table"}

_connection = None
_lock = threading.Lock()


def connection():
    global _connection
    with _lock:
        if _connection is None:
            _connection = duckdb.connect(str(DB_PATH), read_only=True,
                                         config={"enable_external_access": False})
        return _connection


def _plain(value):
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


_catalog_cache = None


def catalog_rows():
    """The catalogue never changes while the app runs, so read it once."""
    global _catalog_cache
    if _catalog_cache is None:
        cur = connection().cursor()
        _catalog_cache = cur.execute("SELECT * FROM catalog").fetchdf().to_dict("records")
    return [dict(row) for row in _catalog_cache]


def table_ids():
    return [row["table_id"] for row in catalog_rows()]


def citation(row):
    return {key: row[key] for key in ["table_id", "survey", "year", "nisr_table_ref", "title", "source_file_url", "report_page_url"]}


def _terms(query):
    words = [w for w in re.findall(r"[a-z0-9]+", query.casefold()) if w not in STOPWORDS]
    terms = set(words)
    for word in words:
        terms.update(SYNONYMS.get(word, []))
        if word.endswith("s") and word[:-1] in SYNONYMS:
            terms.update(SYNONYMS[word[:-1]])
    return words, terms


def search_catalog(query, limit=5):
    """Rank catalog tables by keyword hits (with synonyms) plus fuzzy similarity."""
    words, terms = _terms(query or "")
    scored = []
    for row in catalog_rows():
        primary = f"{row['title']} {row['indicator_name']}".casefold()
        secondary = f"{row['notes']} {row['columns_description']}".casefold()
        score = 0.0
        for term in terms:
            weight = 1.0 if term in words else 0.6
            if re.search(rf"\b{re.escape(term)}", primary):
                score += 2 * weight
            elif re.search(rf"\b{re.escape(term)}", secondary):
                score += 0.5 * weight
        score += fuzz.token_set_ratio(query.casefold(), primary) / 100
        if "district" in (query or "").casefold() and "district" in row["geography_levels"]:
            score += 0.3
        scored.append((score, row))
    scored.sort(key=lambda pair: -pair[0])
    return [{"table_id": r["table_id"], "title": r["title"], "survey": r["survey"], "year": r["year"],
             "nisr_table_ref": r["nisr_table_ref"], "geography_levels": r["geography_levels"],
             "score": round(s, 2)} for s, r in scored[:limit]]


def describe_table(table_id):
    rows = {row["table_id"]: row for row in catalog_rows()}
    if table_id not in rows:
        close = [match for match, _, _ in process.extract(str(table_id), list(rows), limit=3)]
        return {"error": f"Unknown table '{table_id}'. Close matches: {', '.join(close)}", "close_matches": close}
    row = rows[table_id]
    cur = connection().cursor()
    columns = cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
        [table_id]).fetchall()
    order = "CASE geo_level WHEN 'national' THEN 0 WHEN 'district' THEN 1 ELSE 2 END"
    sample = cur.execute(f'SELECT * FROM "{table_id}" ORDER BY {order} LIMIT 5').fetchdf()
    distinct = {}
    for name in ["breakdown", "indicator", "group"]:
        if any(c[0] == name for c in columns):
            values = cur.execute(f'SELECT DISTINCT "{name}" FROM "{table_id}" WHERE "{name}" IS NOT NULL LIMIT 40').fetchall()
            distinct[name] = [v[0] for v in values]
    return {
        "table_id": table_id, "title": row["title"], "unit": row["unit"], "notes": row["notes"],
        "geography_levels": row["geography_levels"],
        "columns": [{"name": n, "type": t} for n, t in columns],
        "column_meanings": row["columns_description"],
        "distinct_values": distinct,
        "sample_rows": [{k: _plain(v) for k, v in r.items()} for r in sample.to_dict("records")],
        "citation": citation(row),
    }


def tables_in_sql(sql, ids=None):
    ids = ids if ids is not None else table_ids()
    lowered = sql.casefold()
    return [t for t in ids if re.search(rf"\b{re.escape(t)}\b", lowered)]


def run_sql(sql):
    """Run one guarded read-only query. Errors are returned, never raised."""
    ok, checked = check_sql(sql)
    if not ok:
        return {"error": checked, "sql": sql}
    cur = connection().cursor()
    timer = threading.Timer(TIMEOUT_SECONDS, cur.interrupt)
    timer.start()
    try:
        cur.execute(checked)
        columns = [d[0] for d in cur.description]
        rows = [[_plain(v) for v in r] for r in cur.fetchmany(MAX_ROWS)]
    except duckdb.InterruptException:
        return {"error": f"Query took longer than {TIMEOUT_SECONDS} seconds.", "sql": checked}
    except duckdb.Error as error:
        return {"error": str(error).split("\n")[0][:400], "sql": checked}
    finally:
        timer.cancel()
    return {"columns": columns, "rows": rows, "row_count": len(rows), "tables_used": tables_in_sql(checked), "sql": checked}


CHART_TYPES = {"bar", "barh", "line", "table", "map"}


def make_chart(result, chart_type, x, y, title=""):
    """Build a Vega-Lite spec from a run_sql result only. The model never supplies the numbers."""
    if not result or "columns" not in result:
        return {"error": "No query result to chart. Run run_sql first."}
    if chart_type not in CHART_TYPES:
        return {"error": f"Unknown chart type '{chart_type}'. Use one of {sorted(CHART_TYPES)}."}
    missing = [c for c in [x, y] if c not in result["columns"]]
    if missing:
        return {"error": f"Columns not in the last result: {missing}. Available: {result['columns']}"}
    xi, yi = result["columns"].index(x), result["columns"].index(y)
    values = [{x: row[xi], y: row[yi]} for row in result["rows"]]
    if chart_type == "table":
        return {"type": "table", "title": title, "columns": result["columns"]}
    if chart_type == "map":
        return {"type": "map", "title": title, "district_field": x, "value_field": y, "values": values}
    quantitative = {"field": y, "type": "quantitative", "title": y.replace("_", " ")}
    category = {"field": x, "type": "nominal" if chart_type != "line" else "ordinal", "title": x.replace("_", " "),
                "sort": None if chart_type == "line" else "-y" if chart_type == "bar" else "-x"}
    encoding = {"x": category, "y": quantitative} if chart_type in {"bar", "line"} else {"y": category, "x": quantitative}
    encoding["tooltip"] = [{"field": x}, {"field": y, "format": ",.2f"}]
    return {
        "type": chart_type, "title": title,
        "spec": {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "title": title,
                 "data": {"values": values}, "mark": {"type": "line" if chart_type == "line" else "bar", "tooltip": True},
                 "encoding": encoding, "width": "container"},
    }
