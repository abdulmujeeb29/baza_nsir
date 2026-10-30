from app.tools import describe_table, make_chart, run_sql, search_catalog


def ids(query, n):
    return [r["table_id"] for r in search_catalog(query)[:n]]


def test_run_sql():
    result = run_sql("SELECT district, value FROM eicv7_a9_23_poverty_rate WHERE geo_level='district' ORDER BY value DESC")
    assert "error" not in result
    assert result["row_count"] == 30
    assert result["rows"][0][0] == "Nyamagabe"
    assert result["tables_used"] == ["eicv7_a9_23_poverty_rate"]
    blocked = run_sql("DROP TABLE catalog")
    assert "error" in blocked
    bad = run_sql("SELECT nope FROM catalog")
    assert "error" in bad
    joined = run_sql("SELECT p.district, p.value, c.counts_both_sexes FROM eicv7_a9_23_poverty_rate p "
                     "JOIN census_t1_population c USING (district) WHERE p.geo_level='district'")
    assert set(joined["tables_used"]) == {"eicv7_a9_23_poverty_rate", "census_t1_population"}


def test_run_sql_no_file_access():
    assert "error" in run_sql("SELECT * FROM 'data/clean/_catalog.csv'")


def test_search():
    assert "eicv7_a9_23_poverty_rate" in ids("poverty by district", 2)
    assert any("electric" in t or "lighting" in t for t in ids("electricity", 3))
    assert {"census_t28_health_insurance", "eicv7_a3_7_health_insurance"} & set(ids("health insurance", 3))
    assert "census_t1_population" in ids("population density", 2)
    assert any(t.startswith("lfs") for t in ids("unemployment rate", 2))


def test_describe():
    for table_id in ["eicv7_a9_23_poverty_rate", "census_t1_population", "lfs_2026q2_indicators_rwanda"]:
        info = describe_table(table_id)
        assert info["columns"] and len(info["sample_rows"]) == 5
        assert info["citation"]["source_file_url"].startswith("https://statistics.gov.rw/")
    unknown = describe_table("eicv7_poverty")
    assert "error" in unknown and unknown["close_matches"]


def test_chart():
    result = run_sql("SELECT district, value FROM eicv7_a9_23_poverty_rate WHERE geo_level='district'")
    chart = make_chart(result, "barh", "district", "value", "Poverty rate by district")
    assert "error" not in chart
    assert len(chart["spec"]["data"]["values"]) == 30
    assert "error" in make_chart(result, "bar", "district", "made_up_column")
    assert "error" in make_chart(result, "pie", "district", "value")
    assert "error" in make_chart(None, "bar", "district", "value")
