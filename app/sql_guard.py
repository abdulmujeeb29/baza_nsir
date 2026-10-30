"""Allow only one read-only SELECT query over the NISR tables."""
import re

MAX_ROWS = 500
BLOCKED_KEYWORDS = ["insert", "update", "delete", "drop", "alter", "create", "attach", "detach", "copy",
                    "pragma", "install", "load", "export", "import", "call", "set", "reset", "truncate",
                    "merge", "grant", "revoke", "vacuum", "checkpoint", "use", "begin",
                    "commit", "rollback", "summarize", "describe", "show"]
BLOCKED_FUNCTIONS = ["read_csv", "read_csv_auto", "read_parquet", "parquet_scan", "read_json", "read_json_auto",
                     "read_ndjson", "read_text", "read_blob", "glob", "csv_scan", "sniff_csv", "getenv",
                     "read_xlsx", "st_read", "query_table", "query", "duckdb_settings", "duckdb_extensions",
                     "duckdb_secrets", "parquet_metadata", "parquet_schema", "iceberg_scan", "delta_scan"]


def _strip_comments(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def _strip_strings(sql):
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def check_sql(sql):
    """Return (ok, reason_or_safe_sql). On success the second item is the SQL to run."""
    if not isinstance(sql, str) or not sql.strip():
        return False, "Empty query."
    if len(sql) > 5000:
        return False, "Query is too long."
    cleaned = _strip_comments(sql).strip()
    if "/*" in cleaned or "*/" in cleaned:
        return False, "Unclosed comment."
    cleaned = cleaned.rstrip().rstrip(";").strip()
    scan = _strip_strings(cleaned)
    if scan.count("'") % 2:
        return False, "Unbalanced quotes."
    if ";" in scan:
        return False, "Only one statement is allowed."
    lowered = scan.casefold()
    if not re.match(r"^\(?\s*(select|with)\b", lowered):
        return False, "Only SELECT queries are allowed."
    for word in BLOCKED_KEYWORDS:
        if re.search(rf"\b{word}\b", lowered):
            return False, f"Keyword not allowed: {word.upper()}."
    for name in BLOCKED_FUNCTIONS:
        if re.search(rf"\b{name}\s*\(", lowered):
            return False, f"Function not allowed: {name}."
    if re.search(r"\b(from|join)\s*\(?\s*'", lowered) or re.search(r"\b(from|join)\s+\"[^\"]*[./\\][^\"]*\"", lowered):
        return False, "Reading files is not allowed."
    if not re.search(r"\blimit\s+\d+", lowered):
        cleaned = f"{cleaned}\nLIMIT {MAX_ROWS}"
    return True, cleaned
