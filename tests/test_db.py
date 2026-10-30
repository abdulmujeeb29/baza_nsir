import pytest

from app.tools import connection
from pipeline.build_db import DB_PATH


@pytest.fixture(scope="module")
def con():
    assert DB_PATH.exists(), "run make data first"
    return connection().cursor()


def test_catalog(con):
    assert con.execute("SELECT count(*) FROM catalog").fetchone()[0] >= 20
    assert con.execute("SELECT count(*) FROM catalog WHERE source_file_url IS NULL").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM catalog WHERE source_file_url NOT LIKE 'https://statistics.gov.rw/%'").fetchone()[0] == 0


def test_indicators_long(con):
    value = con.execute("SELECT value FROM indicators_long WHERE table_id LIKE 'eicv7_a9_23%' AND district='Nyamagabe' AND indicator='value'").fetchone()[0]
    assert round(value, 2) == 51.39


def test_cross_survey_join(con):
    rows = con.execute("""SELECT p.district FROM eicv7_a9_23_poverty_rate p
        JOIN census_t1_population c USING (district) WHERE p.geo_level='district'""").fetchall()
    assert len(rows) == 30


def test_districts(con):
    assert con.execute("SELECT count(*) FROM districts").fetchone()[0] == 30
    assert con.execute("SELECT count(DISTINCT province) FROM districts").fetchone()[0] == 5


def test_every_catalog_table_exists(con):
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    for (table_id,) in con.execute("SELECT table_id FROM catalog").fetchall():
        assert table_id in names
