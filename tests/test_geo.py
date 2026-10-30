from pipeline.geo import DISTRICTS, classify_geo, normalise_name


def test_reference():
    assert len(DISTRICTS) == 30
    assert len({r["district_code"] for r in DISTRICTS}) == 30
    assert len({r["district"] for r in DISTRICTS}) == 30
    assert len({r["province"] for r in DISTRICTS}) == 5


def test_classification():
    assert classify_geo("Nyarugenge") == "district"
    assert classify_geo("City of Kigali ") == "province"
    assert classify_geo("Southern Province") == "province"
    assert classify_geo("Rwanda") == "national"
    assert classify_geo("Urban") == "urban_rural"
    assert classify_geo("All Rwanda") == "national"
    assert classify_geo("unknown place") == "other"


def test_normalisation():
    assert normalise_name("  NYARUGENGE  ") == "nyarugenge"
    assert normalise_name("Kigali City") == normalise_name("City of Kigali")
    assert normalise_name(" Southern   Province ") == "southern"
    assert normalise_name("Gasabo [1]") == "gasabo"
