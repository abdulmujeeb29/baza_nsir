import pytest

from app.sql_guard import check_sql

ALLOWED = [
    "SELECT * FROM catalog",
    "select district, value from eicv7_a9_23_poverty_rate where geo_level = 'district' order by value desc limit 5",
    "WITH p AS (SELECT district, value FROM eicv7_a9_23_poverty_rate) SELECT * FROM p",
    "SELECT * FROM catalog;",
    "SELECT label FROM catalog WHERE title LIKE '%drop table%'",
    "  -- a leading comment\nSELECT 1",
    "SELECT count(*) FROM districts WHERE province = 'City of Kigali'",
    "SELECT district, \"value\" FROM eicv7_a9_23_poverty_rate",
]

BLOCKED = [
    "select * from catalog; drop table x",
    "DROP TABLE catalog",
    "delete from catalog",
    "INSERT INTO catalog VALUES (1)",
    "UPDATE catalog SET title = 'x'",
    "SELECT 1; SELECT 2",
    "ATTACH 'other.db' AS o",
    "COPY catalog TO 'out.csv'",
    "PRAGMA database_list",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM READ_PARQUET('x.parquet')",
    "SELECT * FROM 'data/raw/file.csv'",
    "select * from glob('*')",
    "SELECT 1 /* hidden */; DROP TABLE x",
    "SeLeCt * FrOm catalog; DrOp TaBlE catalog",
    "CREATE TABLE x AS SELECT 1",
    "SET threads = 1",
    "",
    "EXPORT DATABASE 'x'",
    "SELECT getenv('LLM_API_KEY')",
    "SELECT 1 /* unclosed",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql):
    ok, result = check_sql(sql)
    assert ok, result


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocked(sql):
    ok, _ = check_sql(sql)
    assert not ok


def test_limit_added():
    ok, sql = check_sql("SELECT * FROM catalog")
    assert ok and sql.rstrip().endswith("LIMIT 500")


def test_existing_limit_kept():
    ok, sql = check_sql("SELECT * FROM catalog LIMIT 5")
    assert ok and sql.count("LIMIT") == 1


def test_keyword_in_string_is_fine_but_comment_does_not_hide_statement():
    assert check_sql("SELECT 'delete' AS word")[0]
    assert not check_sql("SELECT 1 -- comment\n; DROP TABLE x")[0]
