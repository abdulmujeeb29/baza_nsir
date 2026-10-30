import pytest

from pipeline.parse_excel import clean_number, parse_lfs_sheet, parse_sheet
from pipeline.sources import ROOT

RAW = ROOT / "data/raw"
CENSUS = RAW / "PHC5-2022_Main_Indicators.xlsx"
EICV_MAIN = RAW / "EICV7_Tables_MainIndicatorReport.xlsx"
EICV_UTIL = RAW / "Tables_EICV7_Utilities_Amenities_Thematic_Report.xlsx"
LFS = RAW / "RW_Quarterly_LFS_Tables_2026Q2.xlsx"


def row(frame, label):
    match = frame[frame["label"].str.casefold() == label.casefold()]
    assert len(match) >= 1, f"{label} missing"
    return match.iloc[0]


def test_clean_number():
    assert clean_number("13,246,394") == 13246394
    assert clean_number(" 27.36 ") == 27.36
    assert clean_number("45%") == 45
    assert clean_number("12[1]") == 12
    for blank in ["-", "..", "", None, "District"]:
        assert clean_number(blank) is None


def test_eicv7_a9_23_poverty():
    title, frame = parse_sheet(EICV_MAIN, "Table A9.23", first_col_name="value")
    assert title.startswith("Table A9.23")
    assert round(row(frame, "Nyamagabe")["value"], 2) == 51.39
    assert round(row(frame, "Nyarugenge")["value"], 2) == 6.80
    assert (frame["geo_level"] == "district").sum() == 30
    national = frame[frame["geo_level"] == "national"].iloc[0]
    assert round(national["value"], 2) == 27.36
    assert round(row(frame, "City of Kigali")["value"], 2) == 9.05
    assert {"std_error", "ci_low", "ci_high"} <= set(frame.columns)
    assert row(frame, "Nyamagabe")["province"] == "Southern"
    assert "District" not in set(frame["label"])


def test_census_t1_population():
    title, frame = parse_sheet(CENSUS, "Table 1")
    assert "Resident population" in title
    assert row(frame, "Rwanda")["counts_both_sexes"] == 13246394
    assert row(frame, "Gasabo")["counts_both_sexes"] == 879505
    assert row(frame, "Kicukiro")["population_density"] == 2944
    assert frame[frame.geo_level == "district"]["district"].nunique() == 30


def test_census_t28_insurance():
    _, frame = parse_sheet(CENSUS, "Table 28")
    assert row(frame, "Nyanza")["total_both_sexes"] == 93.4
    assert row(frame, "Rwanda")["total_both_sexes"] == 97.3


def test_util_b07_electricity():
    _, frame = parse_sheet(EICV_UTIL, "Table.B.07")
    assert round(row(frame, "All Rwanda")["value"], 1) == 72.0
    assert round(row(frame, "City of Kigali")["value"], 1) == 91.7


def test_lfs_unemployment():
    _, frame = parse_lfs_sheet(LFS, "LFIndicatorsRw")
    latest = frame[(frame.period == "2026Q2") & frame.indicator.str.startswith("LU1")]
    assert round(latest["value"].iloc[0], 1) == 13.4
