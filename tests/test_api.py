import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.llm import FakeLLM, LLMError


@pytest.fixture()
def client(monkeypatch):
    main.app.state.hits.clear()
    main.app.state.llm_factory = main.demo_llm
    yield TestClient(main.app)
    main.app.state.llm_factory = main.llm_factory


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["tables"] >= 20
    assert "key" not in str(body).casefold()


def test_catalog(client):
    items = client.get("/api/catalog").json()
    assert len(items) >= 20
    assert all(i["source_file_url"].startswith("https://statistics.gov.rw/") for i in items)


def test_ask_returns_citations(client):
    body = client.post("/api/ask", json={"question": "Which district has the highest poverty rate?"}).json()
    assert "Nyamagabe" in body["answer_text"]
    assert body["citations"][0]["nisr_table_ref"] == "Table A9.23"
    assert body["verification"]["status"] == "verified"


def test_question_too_long(client):
    assert client.post("/api/ask", json={"question": "x" * 501}).status_code == 422


def test_rate_limit(client):
    main.app.state.llm_factory = lambda: FakeLLM([])
    codes = [client.post("/api/ask", json={"question": "hello there"}).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20
    assert codes[20] == 429


def test_llm_failure(client):
    main.app.state.llm_factory = lambda: FakeLLM([LLMError("The language model is busy or out of quota. Please try again in a minute.")])
    response = client.post("/api/ask", json={"question": "Which district is poorest?"})
    assert response.status_code == 503
    assert "busy" in response.json()["error"]
    assert "Traceback" not in response.text


def test_unexpected_failure_is_friendly(client):
    main.app.state.llm_factory = lambda: FakeLLM([RuntimeError("boom secret detail")])
    response = client.post("/api/ask", json={"question": "Which district is poorest?"})
    assert response.status_code == 500
    assert "boom" not in response.text


def test_missing_key_is_friendly(client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("APP_ENV", "production")
    main.app.state.llm_factory = main.llm_factory
    response = client.post("/api/ask", json={"question": "Which district is poorest?"})
    assert response.status_code == 503
    assert "API key" in response.json()["error"]


def test_stream_sends_steps_then_result(client, tmp_path, monkeypatch):
    monkeypatch.setenv("QUESTION_LOG_PATH", str(tmp_path / "q.jsonl"))
    with client.stream("POST", "/api/ask/stream", json={"question": "Which district has the highest poverty rate?"}) as response:
        assert response.status_code == 200
        events = [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "step" and kinds[-1] == "result"
    assert any(e.get("tool") == "run_sql" for e in events)
    assert "Nyamagabe" in events[-1]["result"]["answer_text"]


def test_questions_are_logged_without_ip(client, tmp_path, monkeypatch):
    path = tmp_path / "q.jsonl"
    monkeypatch.setenv("QUESTION_LOG_PATH", str(path))
    client.post("/api/ask", json={"question": "Which district has the highest poverty rate?"}, headers={"x-forwarded-for": "203.0.113.9"})
    text = path.read_text()
    assert "highest poverty" in text and "203.0.113.9" not in text
    summary = client.get("/api/gaps").json()
    assert summary["total"] == 1 and summary["answered"] == 1


def test_stream_llm_failure_is_friendly(client):
    main.app.state.llm_factory = lambda: FakeLLM([LLMError("The language model is busy or out of quota. Please try again in a minute.")])
    with client.stream("POST", "/api/ask/stream", json={"question": "Which district is poorest?"}) as response:
        events = [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]
    assert events[-1]["type"] == "error" and "busy" in events[-1]["error"]


def test_brief_validates_district(client):
    assert client.post("/api/brief/stream", json={"district": "Atlantis"}).status_code == 422
    assert len(client.get("/api/districts").json()) == 30


def test_brief_streams_investigation(client):
    captured = {}

    def factory():
        fake = main.demo_llm()
        captured["fake"] = fake
        return fake
    main.app.state.llm_factory = factory
    with client.stream("POST", "/api/brief/stream", json={"district": "nyamagabe"}) as response:
        events = [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]
    result = events[-1]["result"]
    assert result["brief_district"] == "Nyamagabe" and result["mode"] == "investigate"
    question = captured["fake"].calls[0]["messages"][1]["content"]
    assert "Nyamagabe district (Southern Province)" in question and "Imihigo" in question
