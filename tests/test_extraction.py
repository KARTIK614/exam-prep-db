"""ai_anthropic.extract_questions_from_pdf — mocked Anthropic client."""
import json
from unittest.mock import MagicMock, patch


def test_no_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from ai_anthropic import extract_questions_from_pdf
    result = extract_questions_from_pdf(b"%PDF-1.4 fake", "prompt")
    assert result["ok"] is False
    assert "ANTHROPIC_API_KEY" in result["error"]


def test_happy_path_parses_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    fake_response = MagicMock()
    fake_block = MagicMock()
    fake_block.type = "text"
    fake_block.text = json.dumps({
        "questions": [
            {
                "question_text": "Q1?",
                "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
                "correct_option": "A", "explanation": "because A",
                "difficulty": "easy", "confidence": "high",
            }
        ]
    })
    fake_response.content = [fake_block]
    fake_response.usage.input_tokens = 100
    fake_response.usage.output_tokens = 50
    fake_response.usage.cache_read_input_tokens = 0
    fake_response.usage.cache_creation_input_tokens = 0

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = fake_response
        from ai_anthropic import extract_questions_from_pdf
        result = extract_questions_from_pdf(b"%PDF-1.4 fake", "my prompt", topic_hint="History")

    assert result["ok"] is True
    assert len(result["questions"]) == 1
    assert result["questions"][0]["correct_option"] == "A"
    assert result["usage"]["input_tokens"] == 100


def test_malformed_json_returns_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    fake_response = MagicMock()
    fake_block = MagicMock()
    fake_block.type = "text"
    fake_block.text = "not json at all"
    fake_response.content = [fake_block]
    fake_response.usage.input_tokens = 1
    fake_response.usage.output_tokens = 1

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = fake_response
        from ai_anthropic import extract_questions_from_pdf
        result = extract_questions_from_pdf(b"pdf", "prompt")

    assert result["ok"] is False
    assert "parse" in result["error"].lower()
