from app.verifier import extract_numbers, verify

POVERTY = {"columns": ["district", "value"], "row_count": 3,
           "rows": [["Nyamagabe", 51.38916], ["Nyarugenge", 6.79993], ["Gasabo", 11.0587]]}
POPULATION = {"columns": ["label", "counts_both_sexes", "population_density"], "row_count": 2,
              "rows": [["Rwanda", 13246394.0, 503.0], ["Kicukiro", 491731.0, 2944.0]]}


def test_correct_answer_verifies():
    result = verify("Nyamagabe has the highest poverty rate at 51.39%, and Nyarugenge the lowest at 6.80%.", [POVERTY])
    assert result["status"] == "verified" and result["checked"] == 2


def test_invented_number_fails():
    result = verify("Nyamagabe has 51.39% poverty and Huye has 33.3%.", [POVERTY])
    assert result["status"] == "unverified"
    assert result["unmatched"] == ["33.3%"]


def test_rounded_percentage_matches():
    assert verify("About 51.4% of people in Nyamagabe are poor.", [POVERTY])["status"] == "verified"
    assert verify("About 51% of people in Nyamagabe are poor.", [POVERTY])["status"] == "verified"


def test_wrong_rounding_fails():
    assert verify("Nyamagabe poverty is 51.5%.", [POVERTY])["status"] == "unverified"


def test_millions():
    assert verify("Rwanda had 13.2 million residents in 2022.", [POPULATION])["status"] == "verified"
    assert verify("Rwanda had 14.2 million residents.", [POPULATION])["status"] == "unverified"


def test_thousands_separator():
    assert verify("The 2022 census counted 13,246,394 people.", [POPULATION])["status"] == "verified"
    assert verify("Kicukiro has 2,944 people per square km.", [POPULATION])["status"] == "verified"


def test_large_count_relative_tolerance():
    assert verify("Rwanda has about 13,250,000 people.", [POPULATION])["status"] == "verified"


def test_true_ratio_verifies():
    # 51.39 / 11.06 = 4.65
    assert verify("Poverty in Nyamagabe (51.39%) is 4.6 times higher than in Gasabo (11.06%).", [POVERTY])["status"] == "verified"
    assert verify("Poverty in Nyamagabe is 7.9 times higher than in Gasabo.", [POVERTY])["status"] == "unverified"


def test_difference_verifies():
    # 51.39 - 6.80 = 44.59 percentage points
    assert verify("The gap between Nyamagabe and Nyarugenge is 44.6 percentage points.", [POVERTY])["status"] == "verified"


def test_table_refs_and_years_ignored():
    text = "Source: EICV7 2023/24, Table A9.23, and Census 2022 Table 28 and Utilities Table B.07. Nyamagabe: 51.39%."
    result = verify(text, [POVERTY])
    assert result["status"] == "verified"
    assert result["checked"] == 1


def test_rank_and_count_allowed():
    assert verify("The 3 districts are listed below. Nyamagabe ranks 1 with 51.39%.", [POVERTY])["status"] == "verified"


def test_no_numbers():
    result = verify("The loaded NISR tables do not cover HIV prevalence.", [])
    assert result["status"] == "verified" and result["checked"] == 0


def test_numbers_without_results_fail():
    assert verify("HIV prevalence in Musanze is 2.1%.", [])["status"] == "unverified"


def test_extract_numbers():
    values = [n["value"] for n in extract_numbers("51.4%, 13,246,394 and 13.2 million and 2,944")]
    assert values == [51.4, 13246394, 13.2e6, 2944]


def test_confidence_interval_mention_ignored():
    assert verify("With a 95% confidence interval, Nyamagabe is at 51.39%.", [POVERTY])["status"] == "verified"


def test_numbers_from_labels_allowed():
    result = {"columns": ["group", "value"], "row_count": 1, "rows": [["Youth (Age:16-30 years)", 20.5]]}
    assert verify("Youth aged 16 to 30 have an unemployment rate of 20.5%.", [result])["status"] == "verified"


def test_kinyarwanda_confidence_interval_phrase_ignored():
    text = "Nyamagabe ifite 51.39%. Intera y'icyizere ya 95% iri hagati ya 51.39% na 6.80%."
    assert verify(text, [POVERTY])["status"] == "verified"


def test_tags_follow_answer_order_and_point_to_source():
    result = verify("Nyamagabe 51.4%, Kicukiro 2,944 per km2, gap 44.6 points, and 9.9% invented.", [POVERTY, POPULATION])
    assert [t["match"] for t in result["tags"]] == ["direct", "direct", "derived", "unmatched"]
    assert result["tags"][0]["result"] == 0 and result["tags"][1]["result"] == 1
    assert result["checked"] == 3 and result["unmatched"] == ["9.9%"]


def test_years_are_not_tagged():
    result = verify("In the Census 2022, Nyamagabe was at 51.39%.", [POVERTY])
    assert [t["text"] for t in result["tags"]] == ["51.39%"]
