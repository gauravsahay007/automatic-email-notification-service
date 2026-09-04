import os
import json
import pytest
from unittest.mock import patch, MagicMock
from services.gemini_current_affairs.service import (
    get_prompt,
    generate_content_with_gemini,
    create_pdf_from_text,
    check_already_sent,
    mark_as_sent,
    send_email,
    DEFAULT_PROMPT_TEMPLATE,
)

def test_get_prompt_default():
    prompt = get_prompt("September 2026")
    assert "September 2026" in prompt
    assert "Monthly Current Affairs Digest" in prompt

def test_get_prompt_env_var(monkeypatch):
    monkeypatch.setenv(
        "GEMINI_PROMPT_MONTHLY_CURRENT_AFFAIR_PROMPT",
        "Summarize news for {month_year} in details."
    )
    prompt = get_prompt("September 2026")
    assert prompt == "Summarize news for September 2026 in details."

def test_get_prompt_override_cli():
    prompt = get_prompt("September 2026", override_prompt="Custom prompt for {month_year}")
    assert prompt == "Custom prompt for September 2026"

def test_get_prompt_from_file(tmp_path):
    pfile = tmp_path / "custom_prompt.txt"
    pfile.write_text("Prompt from file for {month_year}")
    prompt = get_prompt("September 2026", prompt_file=str(pfile))
    assert prompt == "Prompt from file for September 2026"


@patch("services.gemini_current_affairs.service.GENAI_SDK_AVAILABLE", False)
@patch("services.gemini_current_affairs.service.requests.post")
def test_generate_content_with_gemini_rest(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Generated text content"}]
                }
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value = mock_response

    text = generate_content_with_gemini("Test Prompt", "mock_key")
    assert text == "Generated text content"
    mock_post.assert_called_once()

def test_create_pdf_from_text():
    sample_text = (
        "# Main Title\n"
        "## Subheading\n"
        "- Bullet item 1\n"
        "- Bullet item 2\n\n"
        "Regular paragraph with **bold** text."
    )
    pdf_bytes = create_pdf_from_text(sample_text, "Title Banner")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")

def test_check_already_sent(tmp_path):
    state_file = tmp_path / "state_gemini.json"
    state_file.write_text('{"last_sent": "September 2026"}')

    with patch("services.gemini_current_affairs.service.STATE_FILE", str(state_file)):
        assert check_already_sent("September 2026") is True
        assert check_already_sent("August 2026") is False

def test_mark_as_sent(tmp_path):
    state_file = tmp_path / "state_gemini.json"
    with patch("services.gemini_current_affairs.service.STATE_FILE", str(state_file)):
        mark_as_sent("September 2026")
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["last_sent"] == "September 2026"

@patch("services.gemini_current_affairs.service.resend.Emails.send")
def test_send_email_success(mock_send, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test_key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    monkeypatch.setenv("RESEND_TO_EMAIL", "to@example.com")

    mock_send.return_value = {"id": "gemini-123"}
    send_email(b"%PDF-1.4 mock", "September 2026", "test.pdf", dry_run=False)
    mock_send.assert_called_once()

@patch("services.gemini_current_affairs.service.resend.Emails.send")
def test_send_email_dry_run(mock_send, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test_key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    monkeypatch.setenv("RESEND_TO_EMAIL", "to@example.com")

    send_email(b"%PDF-1.4 mock", "September 2026", "test.pdf", dry_run=True)
    mock_send.assert_not_called()

@patch("services.gemini_current_affairs.service.sys.exit")
def test_send_email_missing_env(mock_exit, monkeypatch):
    mock_exit.side_effect = SystemExit
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        send_email(b"%PDF-1.4 mock", "September 2026", "test.pdf", dry_run=False)
    mock_exit.assert_called_once_with(1)
