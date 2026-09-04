# automatic-email-notification-service

Automated email notification service suite featuring:
1. **Drishti IAS UP State PCS Monthly Consolidation**: Scrapes and sends monthly PDF consolidations.
2. **Gemini Monthly Current Affairs Service**: Generates monthly current affairs digests powered by Google Gemini AI, converts output into styled PDF documents, and emails them.

---

## Services Overview

### 1. Drishti IAS UP State PCS Consolidation

Automatically scrapes the [Drishti IAS Uttar Pradesh State PCS](https://www.drishtiias.com/free-downloads/state-pcs-monthly-consolidation/uttar-pradesh) page once a month, downloads the current month's PDF, and sends it as an email attachment using [Resend](https://resend.com).

#### Schedule & Idempotency
- **Schedule**: GitHub Actions on the **5th of every month at 9:00 AM IST** (`30 3 5 * *` UTC).
- **State File**: `data/state.json` tracks last sent issue.

#### Manual Execution
```bash
python -m services.drishti_up_pcs.service --dry-run
python -m services.drishti_up_pcs.service --target July-2026
```

---

### 2. Gemini Monthly Current Affairs Service

Uses Google Gemini AI to generate monthly current affairs digests (or custom prompted content), parses the response into a formatted PDF document via ReportLab, and mails it using Resend.

#### Configuration & Secrets
- `GEMINI_API_KEY`: API Key for Google Gemini.
- `GEMINI_PROMPT_MONTHLY_CURRENT_AFFAIR_PROMPT`: (Optional) Custom prompt stored in env/secrets. Supports `{month_year}`, `{month}`, `{year}` placeholders.
- `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `RESEND_TO_EMAIL`: Resend credentials.

#### Schedule & Idempotency
- **Schedule**: GitHub Actions on the **1st of every month at 9:30 AM IST** (`0 4 1 * *` UTC).
- **State File**: `data/state_gemini.json` tracks idempotency.

#### Manual Execution
```bash
# Dry run with default prompt
python -m services.gemini_current_affairs.service --dry-run

# Run with custom prompt override
python -m services.gemini_current_affairs.service --prompt "Summarize global science & tech news for {month_year}" --dry-run

# Specify target month & save local PDF
python -m services.gemini_current_affairs.service --target "September 2026" --output-pdf output.pdf --dry-run
```

---

## Local Setup & Testing

1. Setup environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-test.txt
   ```

2. Copy `.env.example` to `.env` and fill in secrets:
   ```bash
   cp .env.example .env
   ```

3. Run test suite:
   ```bash
   pytest
   ```