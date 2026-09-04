import os
import sys
import json
import logging
import argparse
import base64
from datetime import datetime
import re
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import resend

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

# Constants
URL = "https://www.drishtiias.com/free-downloads/state-pcs-monthly-consolidation/uttar-pradesh"
STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "state.json")
MAX_ATTACHMENT_SIZE_MB = 20  # Resend attachment limit

def write_github_summary(title: str, items: list[str]):
    """Write markdown summary to GITHUB_STEP_SUMMARY if running in GitHub Actions."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a") as f:
                f.write(f"## {title}\n")
                for item in items:
                    f.write(f"- {item}\n")
                f.write("\n")
        except Exception as e:
            logger.warning(f"Failed to write GITHUB_STEP_SUMMARY: {e}")

def fetch_page() -> str:
    """Fetch the HTML content of the Drishti IAS page."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/117.0.0.0 Safari/537.36"
    }
    logger.info(f"Fetching page: {URL}")
    response = requests.get(URL, headers=headers, timeout=15)
    response.raise_for_status()
    return response.text

def find_monthly_pdf(html: str, year: int, month_name: str) -> str:
    """
    Parse the HTML and locate the PDF URL for the given year and month.
    Returns the URL string or None if not found.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Find the year section
    year_tag = soup.find(id=str(year))
    if not year_tag:
        logger.warning(f"Could not find year section for {year}.")
        return None
        
    logger.info(f"Found section for year {year}.")
    
    # 2. Find the UL/list following the year section
    ul_tag = year_tag.find_next("ul")
    if not ul_tag:
        logger.warning(f"Could not find list under year section {year}.")
        return None

    # 3. Find the month entry inside the UL
    pdf_url = None
    month_name_lower = month_name.lower()
    
    for li in ul_tag.find_all("li"):
        a_tag = li.find("a")
        if a_tag and a_tag.text:
            text = a_tag.text.strip().lower()
            if month_name_lower in text:
                pdf_url = a_tag.get("href")
                if pdf_url and pdf_url.startswith("/"):
                    pdf_url = "https://www.drishtiias.com" + pdf_url
                break
                
    return pdf_url

def extract_month_year_from_text(text: str) -> str:
    """Extract Month and Year from link text string if present."""
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    found_month = None
    for m in months:
        if m.lower() in text.lower():
            found_month = m
            break
            
    year_match = re.search(r"\b(20\d\d)\b", text)
    if found_month and year_match:
        return f"{found_month} {year_match.group(1)}"
    elif found_month:
        return found_month
    elif year_match:
        return year_match.group(1)
    return None

def find_latest_pdf(html: str) -> tuple[str, str]:
    """
    Parse HTML to find the latest available PDF on the page across all year sections.
    Returns (pdf_url, month_year_str) or (None, None).
    """
    soup = BeautifulSoup(html, "html.parser")
    
    year_tags = []
    for tag in soup.find_all(id=True):
        tid = tag.get("id", "").strip()
        if tid.isdigit() and len(tid) == 4:
            year_tags.append((int(tid), tag))
            
    # Sort years descending (newest first)
    year_tags.sort(key=lambda x: x[0], reverse=True)
    
    for y_num, tag in year_tags:
        ul_tag = tag.find_next("ul")
        if ul_tag:
            for li in ul_tag.find_all("li"):
                a_tag = li.find("a")
                if a_tag and a_tag.get("href"):
                    pdf_url = a_tag.get("href")
                    if pdf_url.startswith("/"):
                        pdf_url = "https://www.drishtiias.com" + pdf_url
                    text = a_tag.text.strip()
                    month_year_str = extract_month_year_from_text(text) or f"Latest {y_num}"
                    return pdf_url, month_year_str
                    
    return None, None

def download_pdf(pdf_url: str) -> bytes:
    """Download the PDF and validate it, with retry support."""
    logger.info(f"Downloading PDF from: {pdf_url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/117.0.0.0 Safari/537.36"
    }
    
    max_retries = 3
    timeout = 90
    content = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Download attempt {attempt}/{max_retries}...")
            response = requests.get(pdf_url, headers=headers, timeout=timeout)
            response.raise_for_status()
            content = response.content
            break
        except Exception as e:
            logger.warning(f"Download attempt {attempt} failed: {e}")
            if attempt == max_retries:
                logger.error(f"Download failed after {max_retries} attempts.")
                raise e
            import time
            time.sleep(3)
    
    # Validate PDF signature
    if not content or not content.startswith(b"%PDF"):
        logger.error("Downloaded content is not a valid PDF (missing %PDF signature).")
        sys.exit(1)
        
    # Check size
    size_mb = len(content) / (1024 * 1024)
    logger.info(f"Downloaded PDF size: {size_mb:.2f} MB")
    
    if size_mb > MAX_ATTACHMENT_SIZE_MB:
        logger.error(f"PDF is too large ({size_mb:.2f} MB) to attach (limit: {MAX_ATTACHMENT_SIZE_MB} MB).")
        sys.exit(1)
        
    return content

def check_already_sent(month_year_str: str) -> bool:
    """Check if the email for this month/year was already sent."""
    if not os.path.exists(STATE_FILE):
        return False
        
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            return state.get("last_sent") == month_year_str
    except Exception as e:
        logger.warning(f"Failed to read state file: {e}")
        return False

def mark_as_sent(month_year_str: str):
    """Mark this month/year as sent in the state file."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state = {"last_sent": month_year_str}
    
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.info(f"Marked {month_year_str} as sent in state file.")
    except Exception as e:
        logger.error(f"Failed to write state file: {e}")
        # Not a hard exit, but will log it

def send_email(pdf_bytes: bytes, month_year_str: str, pdf_filename: str, dry_run: bool):
    """Send the email via Resend with the PDF attached."""
    subject = f"UP State PCS Current Affairs Consolidation - {month_year_str}"
    
    html_content = f"""
    <p>Hello,</p>

    <p>
    Please find attached the
    <strong>State PCS CA Consolidation (Uttar Pradesh) {month_year_str}</strong>.
    </p>

    <p>
    Source:
    <a href="{URL}">
    Drishti IAS - Uttar Pradesh State PCS
    </a>
    </p>

    <p>Regards</p>
    """

    logger.info(f"Email Subject: {subject}")
    
    if dry_run:
        logger.info("DRY RUN: Skipping email send.")
        logger.info(f"Would have attached {pdf_filename} ({len(pdf_bytes)} bytes).")
        return

    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("RESEND_FROM_EMAIL")
    to_email = os.environ.get("RESEND_TO_EMAIL")
    
    if not api_key or not from_email or not to_email:
        logger.error("Missing Resend credentials in environment variables.")
        sys.exit(1)

    resend.api_key = api_key

    logger.info(f"Sending email from {from_email} to {to_email}...")
    
    attachment_content = base64.b64encode(pdf_bytes).decode("utf-8")
    
    params: resend.Emails.SendParams = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
        "attachments": [
            {
                "filename": pdf_filename,
                "content": attachment_content,
            }
        ]
    }

    max_send_retries = 3
    for attempt in range(1, max_send_retries + 1):
        try:
            logger.info(f"Sending email attempt {attempt}/{max_send_retries}...")
            email = resend.Emails.send(params)
            logger.info(f"Email sent successfully! ID: {email.get('id')}")
            return
        except Exception as e:
            logger.error(f"Resend send attempt {attempt} failed: {e}")
            if attempt == max_send_retries:
                sys.exit(1)
            import time
            time.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="Drishti IAS UP State PCS Consolidation Service")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without sending email")
    parser.add_argument("--force", action="store_true", help="Force sending email even if already marked as sent")
    parser.add_argument("--month", type=str, help="Target month name (e.g., July or 07)")
    parser.add_argument("--year", type=int, help="Target year (e.g., 2026)")
    parser.add_argument("--target", type=str, help="Target month-year string (e.g. 'July 2026' or 'July-2026')")
    args = parser.parse_args()
    
    # Load environment variables if .env exists
    load_dotenv()
    
    now = datetime.now()
    year = now.year
    month_name = now.strftime("%B")
    
    if args.target:
        parts = args.target.replace("-", " ").strip().split()
        if len(parts) == 2:
            month_name_input, year_input = parts[0], parts[1]
            if year_input.isdigit():
                year = int(year_input)
            # Try to parse month name if given as number or string
            try:
                if month_name_input.isdigit():
                    month_name = datetime.strptime(month_name_input, "%m").strftime("%B")
                else:
                    month_name = datetime.strptime(month_name_input, "%B").strftime("%B")
            except ValueError:
                # Fallback to title case string if datetime parsing fails (e.g. short month name like Jul)
                try:
                    month_name = datetime.strptime(month_name_input, "%b").strftime("%B")
                except ValueError:
                    month_name = month_name_input.capitalize()
    
    if args.month:
        m = args.month.strip()
        try:
            if m.isdigit():
                month_name = datetime.strptime(m, "%m").strftime("%B")
            else:
                month_name = datetime.strptime(m, "%B").strftime("%B")
        except ValueError:
            try:
                month_name = datetime.strptime(m, "%b").strftime("%B")
            except ValueError:
                month_name = m.capitalize()

    if args.year:
        year = args.year

    month_year_str = f"{month_name} {year}"
    
    logger.info(f"Target: {month_year_str}")
        
    try:
        html = fetch_page()
    except Exception as e:
        logger.error(f"Website unavailable or failed to fetch: {e}")
        sys.exit(1)
        
    pdf_url = find_monthly_pdf(html, year, month_name)
    
    if pdf_url:
        logger.info(f"Target PDF found for {month_year_str}: {pdf_url}")
    else:
        logger.info(f"Current month PDF not available yet ({month_year_str}). Looking for latest available PDF...")
        pdf_url, fallback_month_year = find_latest_pdf(html)
        if not pdf_url:
            logger.error("No PDF available on page.")
            sys.exit(1)
        month_year_str = fallback_month_year
        logger.info(f"Fallback selected latest available PDF: {month_year_str} ({pdf_url})")

    if check_already_sent(month_year_str) and not args.force:
        logger.info(f"Already sent the email for {month_year_str}. Do not send duplicate email. (Use --force to override)")
        write_github_summary("⏭️ Email Skipped (Already Sent)", [
            f"**Target Issue**: {month_year_str}",
            f"**Reason**: Already marked as sent in `data/state.json`.",
            f"**Action**: Pass `force: true` in manual trigger options to resend."
        ])
        sys.exit(0)
        
    # Try to extract a reasonable filename from URL, fallback to default
    pdf_filename = pdf_url.split("/")[-1]
    if not pdf_filename.endswith(".pdf"):
        pdf_filename = f"UP_State_PCS_Consolidation_{month_year_str.replace(' ', '_')}.pdf"
    
    try:
        pdf_bytes = download_pdf(pdf_url)
    except Exception as e:
        logger.error(f"Download failed: {e}")
        write_github_summary("❌ Download Failed", [
            f"**Target Issue**: {month_year_str}",
            f"**URL**: {pdf_url}",
            f"**Error**: {e}"
        ])
        sys.exit(1)
        
    # Send email
    send_email(pdf_bytes, month_year_str, pdf_filename, args.dry_run)
    
    if not args.dry_run:
        mark_as_sent(month_year_str)
        write_github_summary("📧 Email Sent Successfully", [
            f"**Target Issue**: {month_year_str}",
            f"**Attachment**: `{pdf_filename}` ({len(pdf_bytes) / (1024*1024):.2f} MB)",
            f"**Source**: [Drishti IAS Page]({URL})"
        ])
    else:
        write_github_summary("🧪 Dry Run Executed", [
            f"**Target Issue**: {month_year_str}",
            f"**Attachment**: `{pdf_filename}` ({len(pdf_bytes) / (1024*1024):.2f} MB)",
            f"**Note**: Dry run mode - no email was actually sent."
        ])

if __name__ == "__main__":
    main()
