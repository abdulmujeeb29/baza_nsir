import json
from pathlib import Path

from app.agent import _district_map, answer
from app.llm import FakeLLM, LLMResponse, ToolCall
from pipeline.geo import DISTRICTS, normalise_name

ROOT = Path(__file__).resolve().parents[1]


def test_geojson_matches_districts():
    shapes = json.loads((ROOT / "app/static/rwanda_districts.geojson").read_text())
    names = {normalise_name(f["properties"]["district"]) for f in shapes["features"]}
    assert names == {normalise_name(d["district"]) for d in DISTRICTS}
    assert len(shapes["features"]) == 30


def test_poverty_answer_has_map():
    sql = "SELECT district, ROUND(value, 2) AS poverty_rate FROM eicv7_a9_23_poverty_rate WHERE geo_level = 'district'"
    fake = FakeLLM([LLMResponse("", [ToolCall("1", "run_sql", {"sql": sql})]),
                    LLMResponse("", [ToolCall("2", "final_answer", {"answer_text": "Poverty rate by district, highest in Nyamagabe at 51.39%."})])])
    result = answer("Show the poverty rate by district on a map", llm=fake)
    assert result["map"]["value_field"] == "poverty_rate"
    assert len(result["map"]["values"]) == 30


def test_no_map_without_districts():
    result = {"columns": ["label", "value"], "rows": [["Rwanda", 27.4], ["Urban", 16.7]], "row_count": 2}
    assert _district_map(result, None) is None
