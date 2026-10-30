from app.agent import answer, same_numbers
from app.llm import FakeLLM, LLMResponse, ToolCall

SQL = ("SELECT district, ROUND(value, 2) AS poverty_rate FROM eicv7_a9_23_poverty_rate "
       "WHERE geo_level = 'district' ORDER BY value DESC LIMIT 1")


def script(translation):
    return FakeLLM([
        LLMResponse("", [ToolCall("1", "run_sql", {"sql": SQL})]),
        LLMResponse("", [ToolCall("2", "final_answer", {"answer_text": "Nyamagabe has the highest poverty rate, 51.39% (EICV7 2023/24)."})]),
        LLMResponse(translation),
    ])


def test_translated_answer_keeps_numbers():
    fake = script("Akarere ka Nyamagabe ni ko gafite ubukene bwinshi, 51.39% (EICV7 2023/24).")
    result = answer("Ni akahe karere gafite ubukene bwinshi?", llm=fake, lang="rw")
    assert result["language"] == "rw"
    assert "Akarere" in result["answer_text"]
    assert same_numbers(result["answer_text"], result["answer_text_en"])
    assert result["verification"]["status"] == "verified"
    first_user_message = fake.calls[0]["messages"][1]["content"]
    assert first_user_message.startswith("Ni akahe karere gafite ubukene bwinshi?")
    assert "Write final_answer in English" in first_user_message
    assert len(fake.calls) == 3  # agent query, final answer, one translation: no extra call for the question
    assert result["citations"][0]["nisr_table_ref"] == "Table A9.23"


def test_translation_that_changes_a_number_falls_back_to_english():
    result = answer("Ni akahe karere gafite ubukene bwinshi?", llm=script(
        "Akarere ka Nyamagabe ni ko gafite ubukene bwinshi, 51.4% (EICV7 2023/24)."), lang="rw")
    assert result["language"] == "en"
    assert result["answer_text"].startswith("Nyamagabe")
    assert any("translation" in c for c in result["caveats"])


def test_same_numbers():
    assert same_numbers("51.39% and 6.8%", "6.8% na 51.39%")
    assert not same_numbers("51.39%", "51.4%")


def test_same_numbers_counts_ci_and_years():
    english = "Nyamagabe 51.4% in EICV7 2023/24. Its 95% confidence interval was 45.1% to 57.7%."
    kinyarwanda = "Nyamagabe 51.4% muri EICV7 2023/24. Intera y'icyizere ya 95% yari kuva kuri 45.1% kugeza kuri 57.7%."
    assert same_numbers(english, kinyarwanda)
    assert not same_numbers(english, kinyarwanda.replace("57.7", "57.8"))
    assert not same_numbers("51.4%", "51,4%")


def test_translate_answer_switches_and_protects_numbers():
    from app.agent import translate_answer
    english = "Nyamagabe has the highest poverty rate, 51.39% (EICV7 2023/24)."
    good = translate_answer(english, "rw", FakeLLM([LLMResponse("Nyamagabe ifite ubukene bwinshi, 51.39% (EICV7 2023/24).")]))
    assert good["language"] == "rw" and "ifite" in good["answer_text"]
    bad = translate_answer(english, "rw", FakeLLM([LLMResponse("Nyamagabe ifite ubukene bwinshi, 52% (EICV7 2023/24).")]))
    assert bad["language"] == "en" and bad["answer_text"] == english and bad["note"]
    assert translate_answer(english, "en", FakeLLM([]))["answer_text"] == english


def test_translate_endpoint():
    from fastapi.testclient import TestClient
    from app import main
    main.app.state.hits.clear()
    main.app.state.llm_factory = lambda: FakeLLM([LLMResponse("Nyamagabe ifite 51.39%.")])
    try:
        client = TestClient(main.app)
        body = client.post("/api/translate", json={"text": "Nyamagabe has 51.39%.", "target": "rw"}).json()
        assert body["language"] == "rw"
        assert client.post("/api/translate", json={"text": "x", "target": "fr"}).status_code == 422
    finally:
        main.app.state.llm_factory = main.llm_factory
