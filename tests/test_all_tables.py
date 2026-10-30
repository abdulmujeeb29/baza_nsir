import pandas as pd
import pytest

from pipeline.build_db import GEO_COLUMNS, parse_table
from pipeline.tables import TABLES


@pytest.mark.parametrize("entry", TABLES, ids=[t["table_id"] for t in TABLES])
def test_table_parses(entry):
    title, frame = parse_table(entry)
    assert title
    assert len(frame) > 0
    numeric = [c for c in frame.columns if c not in GEO_COLUMNS and pd.api.types.is_numeric_dtype(frame[c])]
    assert numeric, "no numeric columns"
    if "district" in entry["geography_levels"]:
        districts = frame.loc[frame["geo_level"] == "district", "district"]
        assert districts.nunique() == 30


def test_registry_has_priority_tables():
    ids = {t["table_id"] for t in TABLES}
    assert len(ids) == len(TABLES) >= 20
    for needed in ["eicv7_a9_23_poverty_rate", "census_t1_population", "census_t28_health_insurance"]:
        assert needed in ids
