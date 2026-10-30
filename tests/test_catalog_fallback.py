from app import agent, nisr_catalog
from app.llm import FakeLLM, LLMResponse, ToolCall

POINTERS = [{"title": "Demographic and Health Survey 2019-2020", "years": "2019-2020", "type": "survey",
             "idno": "RWA-DHS-2019", "url": "https://example.org/catalog/1", "abstract": "HIV, nutrition"}]


def test_catalog_tool_returns_pointers(monkeypatch):
    monkeypatch.setattr(nisr_catalog, "search", lambda q, limit=5: POINTERS)
    fake = FakeLLM([
        LLMResponse("", [ToolCall("1", "search_nisr_catalog", {"query": "HIV prevalence"})]),
        LLMResponse("", [ToolCall("2", "final_answer", {"answer_text": "Not in the loaded tables. See the Demographic and Health Survey 2019-2020 in NISR's catalogue."})]),
    ])
    result = agent.answer("What is the HIV prevalence in Musanze?", llm=fake)
    assert result["catalog_pointers"][0]["idno"] == "RWA-DHS-2019"
    assert result["verification"]["status"] == "verified"
    assert any("microdata catalogue" in s["detail"] for s in result["steps"])


def test_empty_model_reply_falls_back_to_pointers(monkeypatch):
    monkeypatch.setattr(nisr_catalog, "search", lambda q, limit=5: POINTERS)
    fake = FakeLLM([LLMResponse("", [ToolCall("1", "search_nisr_catalog", {"query": "HIV"})]), LLMResponse(""), LLMResponse("")])
    result = agent.answer("HIV in Musanze?", llm=fake)
    assert "Demographic and Health Survey 2019-2020" in result["answer_text"]
    assert "Please call final_answer" in fake.calls[2]["messages"][-1]["content"]


def test_catalog_outage_is_reported_not_raised(monkeypatch):
    def broken(q, limit=5):
        raise nisr_catalog.CatalogError("NISR catalogue unavailable: ConnectError")
    monkeypatch.setattr(nisr_catalog, "search", broken)
    fake = FakeLLM([LLMResponse("", [ToolCall("1", "search_nisr_catalog", {"query": "HIV"})]),
                    LLMResponse("", [ToolCall("2", "final_answer", {"answer_text": "Not available here."})])])
    result = agent.answer("HIV?", llm=fake)
    assert "unavailable" in fake.calls[1]["messages"][-1]["content"]
    assert result["answer_text"] == "Not available here."


def test_survey_links_go_to_nisr_public_catalogue(monkeypatch):
    fake_result = {"items": [
        {"title": "DHS 2019-2020", "year_start": "2019", "year_end": "2020", "type": "survey", "idno": "rwa-nisr-rdhs6-2019-2020-v01",
         "url": "https://training.ihsn.org/index.php/catalog/862", "abstract": "x"},
        {"title": "District profile", "year_start": "2019", "year_end": "2019", "type": "document", "idno": "doc-1",
         "url": "https://training.ihsn.org/index.php/catalog/28", "abstract": "y"}]}
    monkeypatch.setattr(nisr_catalog, "call_tool", lambda name, args: fake_result)
    items = nisr_catalog.search("HIV")
    assert items[0]["url"] == "https://microdata.statistics.gov.rw/index.php/catalog/study/rwa-nisr-rdhs6-2019-2020-v01"
    assert items[1]["url"] == "https://training.ihsn.org/index.php/catalog/28"
    assert items[0]["years"] == "2019-2020"
