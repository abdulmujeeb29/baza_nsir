from app.agent import answer
from app.llm import FakeLLM, LLMResponse, ToolCall

POVERTY_SQL = ("SELECT district, ROUND(value, 2) AS poverty_rate FROM eicv7_a9_23_poverty_rate "
               "WHERE geo_level = 'district' ORDER BY value DESC LIMIT 5")


def call(name, **args):
    return LLMResponse("", [ToolCall(f"id_{name}", name, args)])


def final(text, caveats=None):
    return call("final_answer", answer_text=text, caveats=caveats or [])


def test_happy_path():
    fake = FakeLLM([
        call("search_catalog", query="poverty by district"),
        call("describe_table", table_id="eicv7_a9_23_poverty_rate"),
        call("run_sql", sql=POVERTY_SQL),
        call("make_chart", chart_type="barh", x="district", y="poverty_rate", title="Poverty"),
        final("Nyamagabe has the highest poverty rate, 51.39% (EICV7 2023/24, Table A9.23)."),
    ])
    result = answer("Which district has the highest poverty rate?", llm=fake)
    assert "Nyamagabe" in result["answer_text"]
    assert result["citations"][0]["nisr_table_ref"] == "Table A9.23"
    assert result["citations"][0]["source_file_url"].startswith("https://statistics.gov.rw/")
    assert result["verification"]["status"] == "verified"
    assert result["chart"]["type"] == "barh"
    assert result["table_rows"]["rows"][0][0] == "Nyamagabe"
    assert len(result["sql"]) == 1
    assert [s["tool"] for s in result["steps"]] == ["search_catalog", "search_catalog", "describe_table", "run_sql", "make_chart", "verify"]
    assert "Pre-selected likely tables" in result["steps"][0]["detail"] and "eicv7_a9_23_poverty_rate" in result["steps"][0]["detail"]
    assert "eicv7_a9_23_poverty_rate" in fake.calls[0]["messages"][1]["content"]


def test_events_are_emitted_live():
    events = []
    fake = FakeLLM([call("run_sql", sql=POVERTY_SQL), final("Nyamagabe is highest at 51.39%.")])
    answer("Highest poverty?", llm=fake, on_event=events.append)
    tools = [e["tool"] for e in events if e["type"] == "step"]
    assert tools == ["plan", "search_catalog", "run_sql", "verify"]


def test_sql_error_then_retry():
    fake = FakeLLM([
        call("run_sql", sql="SELECT district, poverty FROM eicv7_a9_23_poverty_rate"),
        call("run_sql", sql=POVERTY_SQL),
        final("Nyamagabe is highest at 51.4%."),
    ])
    result = answer("Highest poverty?", llm=fake)
    tool_messages = [m for m in fake.calls[1]["messages"] if m["role"] == "tool"]
    assert "error" in tool_messages[0]["content"]
    assert result["verification"]["status"] == "verified"
    assert len(result["sql"]) == 1


def test_sql_retry_limit():
    bad = "SELECT nope FROM catalog"
    fake = FakeLLM([call("run_sql", sql=bad), call("run_sql", sql=bad), call("run_sql", sql=POVERTY_SQL),
                    final("I could not query the data.")])
    result = answer("x", llm=fake)
    assert result["sql"] == []


def test_refusal_without_tables():
    fake = FakeLLM([
        call("search_catalog", query="HIV prevalence"),
        final("The NISR tables loaded here do not cover HIV prevalence. The Rwanda DHS in the NISR microdata catalogue does."),
    ])
    result = answer("What is the HIV prevalence in Musanze?", llm=fake)
    assert result["citations"] == []
    assert result["answered_from_data"] is False
    assert result["verification"]["status"] == "verified"
    assert result["chart"] is None


def test_self_correction():
    fake = FakeLLM([
        call("run_sql", sql=POVERTY_SQL),
        final("Nyamagabe is highest at 61.2%."),
        final("Nyamagabe is highest at 51.39%."),
    ])
    result = answer("Highest poverty?", llm=fake)
    assert result["verification"]["status"] == "verified"
    assert result["verification"]["self_corrected"] is True
    assert "51.39" in result["answer_text"]
    correction_prompt = fake.calls[2]["messages"][-1]["content"]
    assert "61.2%" in correction_prompt


def test_self_correction_still_wrong_is_flagged():
    fake = FakeLLM([call("run_sql", sql=POVERTY_SQL), final("It is 61.2%."), final("It is 62.0%.")])
    result = answer("Highest poverty?", llm=fake)
    assert result["verification"]["status"] == "unverified"
    assert result["verification"]["unmatched"] == ["62.0%"]


def test_kinyarwanda_question_does_not_crash():
    fake = FakeLLM([call("run_sql", sql=POVERTY_SQL), final("Akarere ka Nyamagabe gafite ubukene bwinshi: 51.39%.")])
    result = answer("Ni akahe karere gafite ubukene bwinshi?", llm=fake)
    assert "Nyamagabe" in result["answer_text"]
    assert result["verification"]["status"] == "verified"


def test_plain_text_answer_is_accepted():
    fake = FakeLLM([LLMResponse("Out of scope: NISR tables do not predict elections.")])
    result = answer("Who will win the next election?", llm=fake)
    assert "Out of scope" in result["answer_text"]


def test_investigation_mode_plans_and_cites_many_tables():
    events = []
    join_sql = ("SELECT p.district, ROUND(p.value, 1) AS poverty, ROUND(e.value, 1) AS electricity "
                "FROM eicv7_a9_23_poverty_rate p JOIN eicv7_a5_14_electricity_lighting e USING (district) "
                "WHERE p.district = 'Nyamagabe'")
    fake = FakeLLM([
        call("plan", steps=["Poverty level", "Electricity access"]),
        call("run_sql", sql=join_sql),
        final("Nyamagabe is behind.\n- Poverty: 51.4% (EICV7 2023/24).\n- Electricity: 58.2% (EICV7 2023/24).\nWhere to act: electricity."),
    ])
    result = answer("Investigate Nyamagabe", llm=fake, mode="investigate", on_event=events.append)
    assert result["mode"] == "investigate" and result["plan"] == ["Poverty level", "Electricity access"]
    assert {"plan"} <= {e["type"] for e in events}
    assert "INVESTIGATION MODE" in fake.calls[0]["messages"][0]["content"]
    assert {c["nisr_table_ref"] for c in result["citations"]} == {"Table A9.23", "Table A5.14"}
    assert result["verification"]["status"] == "verified"
    assert result["queries"][0]["rows"][0][0] == "Nyamagabe"


def test_number_tags_carry_table_reference():
    fake = FakeLLM([call("run_sql", sql=POVERTY_SQL), final("Nyamagabe is highest at 51.39%.")])
    result = answer("Highest poverty?", llm=fake)
    assert result["number_tags"] == [{"text": "51.39%", "match": "direct", "ref": "A9.23"}]


def test_joined_query_numbers_point_to_query_not_a_guessed_table():
    join_sql = ("SELECT p.district, ROUND(p.value, 2) AS poverty, ROUND(e.value, 1) AS electricity "
                "FROM eicv7_a9_23_poverty_rate p JOIN eicv7_a5_14_electricity_lighting e USING (district) WHERE p.district = 'Nyamagabe'")
    fake = FakeLLM([call("run_sql", sql=POVERTY_SQL), call("run_sql", sql=join_sql),
                    final("Nyamagabe: poverty 51.39%, electricity 58.2%.")])
    result = answer("Nyamagabe?", llm=fake)
    assert [t["ref"] for t in result["number_tags"]] == ["A9.23", "Q2"]
