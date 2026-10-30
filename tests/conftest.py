import pytest


@pytest.fixture(autouse=True)
def isolated_question_log(tmp_path, monkeypatch):
    """Tests never write to the real question log."""
    monkeypatch.setenv("QUESTION_LOG_PATH", str(tmp_path / "questions.jsonl"))
