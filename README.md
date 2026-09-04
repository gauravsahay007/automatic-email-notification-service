# automatic-email-notification-service

A service to automatically fetch and email the Drishti IAS UP State PCS Monthly Consolidation PDFs, and can be extended for other automated notifications.

## Drishti IAS UP State PCS Consolidation

Automatically scrapes the [Drishti IAS Uttar Pradesh State PCS](https://www.drishtiias.com/free-downloads/state-pcs-monthly-consolidation/uttar-pradesh) page once a month, downloads the current month's PDF, and sends it as an email attachment using [Resend](https://resend.com).

### Monthly Schedule
Runs automatically via GitHub Actions on the **5th of every month at 9:00 AM IST** (`0 3 * * *` UTC).

### Duplicate Email Behavior
The service maintains a local `data/state.json` file to track the last sent month. This state file is committed back to the repository via the GitHub Actions runner to ensure duplicate emails are not sent even if the workflow is triggered manually.

### Behavior when Current Month is Unavailable
If the workflow runs but the Drishti IAS page has not yet published the PDF for the current month, the service automatically falls back to finding and sending the **last updated (latest available) PDF** on the page. If that latest PDF has already been sent previously, it skips sending a duplicate email and exits cleanly.

### Required Environment Variables
The following environment variables (or GitHub Secrets) are required:
- `RESEND_API_KEY`: Your Resend API key (e.g., `re_123456789`)
- `RESEND_FROM_EMAIL`: The sender email address (e.g., `notifications@example.com`)
- `RESEND_TO_EMAIL`: The recipient email address (e.g., `recipient@example.com`)

### Local Setup
1. Clone the repository and navigate into it.
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy the `.env.example` file to `.env`: `cp .env.example .env`
6. Fill in the `.env` file with your actual values. **Important: Never commit the `.env` file!**

### How to Run Manually
Run for the current month:
```bash
python -m services.drishti_up_pcs.service
```

Run for a specific month and year:
```bash
python -m services.drishti_up_pcs.service --target July-2026
# or
python -m services.drishti_up_pcs.service --month July --year 2026
```

### How to Perform a Dry Run
A dry run will scrape the page, download and validate the PDF, and print the email content without actually sending the email.
```bash
# Dry run for current month
python -m services.drishti_up_pcs.service --dry-run

# Dry run for a specific month
python -m services.drishti_up_pcs.service --target July-2026 --dry-run
```

### GitHub Actions
The workflow is defined in `.github/workflows/drishti-up-pcs.yml`.
It requires the following GitHub Repository Secrets to be set up:
- `RESEND_API_KEY`
- `RESEND_FROM_EMAIL`
- `RESEND_TO_EMAIL`