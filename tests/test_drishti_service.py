import os
import pytest
from unittest.mock import patch, MagicMock
from services.drishti_up_pcs.service import (
    fetch_page,
    find_monthly_pdf,
    find_latest_pdf,
    extract_month_year_from_text,
    download_pdf,
    check_already_sent,
    mark_as_sent,
    send_email
)

MOCK_HTML_SUCCESS = """
<html>
    <head><title>Test</title></head>
    <body>
        <div id="2026">
            <h2>2026</h2>
        </div>
        <ul>
            <li>
                <a href="https://www.drishtiias.com/images/pdf/september-2026.pdf">State PCS CA Consolidation (Uttar Pradesh) September 2026</a>
            </li>
            <li>
                <a href="/images/pdf/august-2026.pdf">State PCS CA Consolidation (Uttar Pradesh) August 2026</a>
            </li>
        </ul>
        <div id="2025">
            <h2>2025</h2>
        </div>
        <ul>
            <li>
                <a href="https://www.drishtiias.com/images/pdf/september-2025.pdf">State PCS CA Consolidation (Uttar Pradesh) September 2025</a>
            </li>
        </ul>
    </body>
</html>
"""

MOCK_HTML_MISSING_MONTH = """
<html>
    <body>
        <div id="2026"></div>
        <ul>
            <li>
                <a href="https://www.drishtiias.com/images/pdf/august-2026.pdf">State PCS CA Consolidation (Uttar Pradesh) August 2026</a>
            </li>
        </ul>
    </body>
</html>
"""

def test_find_monthly_pdf_success():
    url = find_monthly_pdf(MOCK_HTML_SUCCESS, 2026, "September")
    assert url == "https://www.drishtiias.com/images/pdf/september-2026.pdf"

def test_find_monthly_pdf_relative_url():
    url = find_monthly_pdf(MOCK_HTML_SUCCESS, 2026, "August")
    assert url == "https://www.drishtiias.com/images/pdf/august-2026.pdf"

def test_find_monthly_pdf_missing_month():
    url = find_monthly_pdf(MOCK_HTML_MISSING_MONTH, 2026, "September")
    assert url is None

def test_find_monthly_pdf_missing_year():
    url = find_monthly_pdf(MOCK_HTML_SUCCESS, 2030, "September")
    assert url is None

def test_find_latest_pdf():
    url, month_year = find_latest_pdf(MOCK_HTML_SUCCESS)
    assert url == "https://www.drishtiias.com/images/pdf/september-2026.pdf"
    assert month_year == "September 2026"

def test_extract_month_year_from_text():
    assert extract_month_year_from_text("State PCS CA Consolidation (Uttar Pradesh) July 2026") == "July 2026"
    assert extract_month_year_from_text("State PCS CA Consolidation (Uttar Pradesh) – December 2021") == "December 2021"

@patch("services.drishti_up_pcs.service.requests.get")
def test_fetch_page(mock_get):
    mock_response = MagicMock()
    mock_response.text = "<html></html>"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    html = fetch_page()
    assert html == "<html></html>"
    mock_get.assert_called_once()
    mock_response.raise_for_status.assert_called_once()

@patch("services.drishti_up_pcs.service.requests.get")
def test_download_pdf_success(mock_get):
    mock_response = MagicMock()
    mock_response.content = b"%PDF-1.4 mock content here"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    content = download_pdf("http://example.com/mock.pdf")
    assert content == b"%PDF-1.4 mock content here"
    mock_get.assert_called_once()

@patch("services.drishti_up_pcs.service.sys.exit")
@patch("services.drishti_up_pcs.service.requests.get")
def test_download_pdf_invalid_signature(mock_get, mock_exit):
    mock_exit.side_effect = SystemExit
    mock_response = MagicMock()
    mock_response.content = b"<html>Not a PDF</html>"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    with pytest.raises(SystemExit):
        download_pdf("http://example.com/mock.pdf")
    mock_exit.assert_called_once_with(1)

def test_check_already_sent(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text('{"last_sent": "September 2026"}')
    
    with patch("services.drishti_up_pcs.service.STATE_FILE", str(state_file)):
        assert check_already_sent("September 2026") is True
        assert check_already_sent("August 2026") is False

def test_mark_as_sent(tmp_path):
    state_file = tmp_path / "state.json"
    with patch("services.drishti_up_pcs.service.STATE_FILE", str(state_file)):
        mark_as_sent("October 2026")
        assert state_file.exists()
        import json
        data = json.loads(state_file.read_text())
        assert data["last_sent"] == "October 2026"

@patch("services.drishti_up_pcs.service.resend.Emails.send")
def test_send_email_success(mock_send, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test_key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    monkeypatch.setenv("RESEND_TO_EMAIL", "to@example.com")
    
    mock_send.return_value = {"id": "123"}
    
    send_email(b"%PDF...", "September 2026", "test.pdf", dry_run=False)
    mock_send.assert_called_once()

@patch("services.drishti_up_pcs.service.resend.Emails.send")
def test_send_email_dry_run(mock_send, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test_key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    monkeypatch.setenv("RESEND_TO_EMAIL", "to@example.com")
    
    send_email(b"%PDF...", "September 2026", "test.pdf", dry_run=True)
    mock_send.assert_not_called()

@patch("services.drishti_up_pcs.service.sys.exit")
def test_send_email_missing_env(mock_exit, monkeypatch):
    mock_exit.side_effect = SystemExit
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        send_email(b"%PDF...", "September 2026", "test.pdf", dry_run=False)
    mock_exit.assert_called_once_with(1)
