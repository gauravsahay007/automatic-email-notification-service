import os
import sys
import json
import logging
import argparse
import base64
import re
from datetime import datetime
from io import BytesIO
import requests
from dotenv import load_dotenv
import resend

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Try importing google.genai SDK if available
try:
    from google import genai
    GENAI_SDK_AVAILABLE = True
except ImportError:
    GENAI_SDK_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

# Constants
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
STATE_FILE = os.path.join(BASE_DIR, "data", "state_gemini.json")
PROMPT_FILE_ROOT = os.path.join(BASE_DIR, "gemini_prompt_monthly_current_affair_prompt.txt")
PROMPT_FILE_DIR = os.path.join(BASE_DIR, "prompts", "gemini_prompt_monthly_current_affair_prompt.txt")
MAX_ATTACHMENT_SIZE_MB = 20

DEFAULT_PROMPT_TEMPLATE = (
    "Provide a comprehensive, well-structured Monthly Current Affairs Digest for {month_year}.\n"
    "Cover the following sections:\n"
    "1. National & International News Highlights\n"
    "2. Economy & Business Developments\n"
    "3. Science, Technology & Environment\n"
    "4. Government Schemes & Policies\n"
    "5. Important Dates & Awards\n\n"
    "Format the response clearly using section titles, subheadings, and bullet points."
)


def read_prompt_file(custom_path: str = None) -> str:
    """Read prompt text from file if available."""
    paths_to_check = []
    if custom_path:
        paths_to_check.append(custom_path)
    env_file = os.environ.get("GEMINI_PROMPT_MONTHLY_CURRENT_AFFAIR_FILE")
    if env_file:
        paths_to_check.append(env_file)
    paths_to_check.extend([PROMPT_FILE_ROOT, PROMPT_FILE_DIR])

    for path in paths_to_check:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        logger.info(f"Loaded prompt from file: {path}")
                        return content
            except Exception as e:
                logger.warning(f"Failed to read prompt file '{path}': {e}")
    return None


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


def get_prompt(month_year_str: str, override_prompt: str = None, prompt_file: str = None) -> str:
    """
    Determine prompt string.
    Priority:
    1. override_prompt CLI argument
    2. Read from prompt .txt file (gemini_prompt_monthly_current_affair_prompt.txt)
    3. GEMINI_PROMPT_MONTHLY_CURRENT_AFFAIR_PROMPT environment variable
    4. DEFAULT_PROMPT_TEMPLATE fallback
    """
    raw_prompt = (
        override_prompt
        or os.environ.get("GEMINI_PROMPT_MONTHLY_CURRENT_AFFAIR_PROMPT")
        or read_prompt_file(prompt_file)
        or DEFAULT_PROMPT_TEMPLATE
    )


    if "{month_year}" in raw_prompt:
        return raw_prompt.format(month_year=month_year_str)
    elif "{month}" in raw_prompt or "{year}" in raw_prompt:
        parts = month_year_str.split(" ")
        m_val = parts[0] if len(parts) > 0 else month_year_str
        y_val = parts[1] if len(parts) > 1 else ""
        return raw_prompt.format(month=m_val, year=y_val, month_year=month_year_str)
    else:
        # If no placeholder, append target timeframe if default/custom doesn't state it
        if month_year_str.lower() not in raw_prompt.lower():
            return f"{raw_prompt}\n\n(Target period: {month_year_str})"
        return raw_prompt



def generate_content_with_gemini(prompt: str, api_key: str, model_name: str = "gemini-3.6-flash") -> str:
    """Generate content from Gemini API using google.genai SDK or REST API fallback."""
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not provided.")

    logger.info(f"Generating content using Gemini model '{model_name}'...")

    if GENAI_SDK_AVAILABLE:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response and response.text:
                return response.text
        except Exception as e:
            logger.warning(f"google-genai SDK call failed, falling back to REST API: {e}")

    # Fallback to direct REST API call
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    res_data = response.json()

    try:
        candidates = res_data.get("candidates", [])
        parts = candidates[0]["content"]["parts"]
        text_content = "".join([part.get("text", "") for part in parts])
        if text_content.strip():
            return text_content
        raise ValueError("Empty response text from Gemini REST API.")
    except (IndexError, KeyError, TypeError) as e:
        logger.error(f"Unexpected Gemini API response structure: {res_data}")
        raise ValueError(f"Failed to parse Gemini API response: {e}")


def create_pdf_from_text(text_content: str, title_str: str) -> bytes:
    """
    Convert text/markdown output into a clean PDF document using ReportLab.
    """
    logger.info("Generating PDF document from generated content...")
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=12,
    )

    h1_style = ParagraphStyle(
        "DocH1",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=12,
        spaceAfter=6,
    )

    h2_style = ParagraphStyle(
        "DocH2",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#2D3748"),
        spaceBefore=8,
        spaceAfter=4,
    )

    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=6,
    )

    bullet_style = ParagraphStyle(
        "DocBullet",
        parent=body_style,
        leftIndent=15,
        spaceAfter=4,
    )

    story = []

    # Title Banner
    story.append(Paragraph(title_str, title_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=15))

    # Helper function to clean markdown bold/italic tags into ReportLab XML tags
    def format_inline_markdown(line_text: str) -> str:
        # Escape XML characters first
        safe_text = line_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # Convert **bold** to <b>bold</b>
        safe_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", safe_text)
        # Convert *italic* or _italic_ to <i>italic</i>
        safe_text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", safe_text)
        return safe_text

    lines = text_content.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 4))
            continue

        if stripped.startswith("# "):
            h_text = format_inline_markdown(stripped[2:].strip())
            story.append(Paragraph(h_text, h1_style))
        elif stripped.startswith("## "):
            h_text = format_inline_markdown(stripped[3:].strip())
            story.append(Paragraph(h_text, h1_style))
        elif stripped.startswith("### "):
            h_text = format_inline_markdown(stripped[4:].strip())
            story.append(Paragraph(h_text, h2_style))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            b_text = format_inline_markdown(stripped[2:].strip())
            story.append(Paragraph(f"&bull; {b_text}", bullet_style))
        elif re.match(r"^\d+\.\s", stripped):
            b_text = format_inline_markdown(re.sub(r"^\d+\.\s", "", stripped))
            num = stripped.split(".")[0]
            story.append(Paragraph(f"<b>{num}.</b> {b_text}", bullet_style))
        else:
            p_text = format_inline_markdown(stripped)
            story.append(Paragraph(p_text, body_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    size_mb = len(pdf_bytes) / (1024 * 1024)
    logger.info(f"Generated PDF size: {size_mb:.2f} MB")

    if size_mb > MAX_ATTACHMENT_SIZE_MB:
        raise ValueError(f"Generated PDF exceeds maximum allowed size ({size_mb:.2f} MB > {MAX_ATTACHMENT_SIZE_MB} MB)")

    return pdf_bytes


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
    state = {"last_sent": month_year_str, "timestamp": datetime.now().isoformat()}

    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.info(f"Marked '{month_year_str}' as sent in {STATE_FILE}.")
    except Exception as e:
        logger.error(f"Failed to write state file: {e}")


def send_email(pdf_bytes: bytes, month_year_str: str, pdf_filename: str, dry_run: bool):
    """Send the email via Resend with the PDF attached."""
    subject = f"Gemini Monthly Current Affairs Digest - {month_year_str}"

    html_content = f"""
    <p>Hello,</p>

    <p>
    Please find attached your AI-generated <strong>Monthly Current Affairs Digest for {month_year_str}</strong>,
    powered by Google Gemini.
    </p>

    <p>The attached PDF contains structured highlights, key policy developments, and national/international news summary.</p>

    <p>Regards,<br>Automated Gemini Notification Service</p>
    """

    logger.info(f"Email Subject: {subject}")

    if dry_run:
        logger.info("DRY RUN: Skipping actual email send.")
        logger.info(f"Would have attached {pdf_filename} ({len(pdf_bytes)} bytes).")
        return

    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("RESEND_FROM_EMAIL")
    to_email = os.environ.get("RESEND_TO_EMAIL")

    if not api_key or not from_email or not to_email:
        logger.error("Missing Resend credentials (RESEND_API_KEY, RESEND_FROM_EMAIL, RESEND_TO_EMAIL).")
        sys.exit(1)

    resend.api_key = api_key
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
        ],
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
    parser = argparse.ArgumentParser(description="Gemini Monthly Current Affairs Email Service")
    parser.add_argument("--prompt", type=str, help="Custom prompt string for Gemini API")
    parser.add_argument("--prompt-file", type=str, help="Path to text file containing prompt template")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without sending email")
    parser.add_argument("--force", action="store_true", help="Force execution even if already sent")
    parser.add_argument("--month", type=str, help="Target month name (e.g. September)")
    parser.add_argument("--year", type=int, help="Target year (e.g. 2026)")
    parser.add_argument("--target", type=str, help="Target month-year string (e.g. 'September 2026')")
    parser.add_argument("--output-pdf", type=str, help="Optional path to save generated PDF locally")
    args = parser.parse_args()

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
            try:
                if month_name_input.isdigit():
                    month_name = datetime.strptime(month_name_input, "%m").strftime("%B")
                else:
                    month_name = datetime.strptime(month_name_input, "%B").strftime("%B")
            except ValueError:
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
    logger.info(f"Target Period: {month_year_str}")

    if check_already_sent(month_year_str) and not args.force:
        logger.info(f"Already sent email for '{month_year_str}'. Skipping. (Use --force to override)")
        write_github_summary("⏭️ Gemini Email Skipped (Already Sent)", [
            f"**Target Period**: {month_year_str}",
            f"**Reason**: Already marked as sent in `data/state_gemini.json`.",
            f"**Action**: Set `force: true` to resend."
        ])
        sys.exit(0)

    prompt = get_prompt(month_year_str, args.prompt, args.prompt_file)

    logger.info(f"Prompt to be sent to Gemini:\n{prompt}")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key and not args.dry_run:
        logger.error("GEMINI_API_KEY environment variable is missing.")
        sys.exit(1)

    if args.dry_run and not gemini_key:
        logger.info("DRY RUN without GEMINI_API_KEY: Using mock Gemini response content.")
        generated_text = (
            f"# Monthly Current Affairs Digest - {month_year_str}\n\n"
            "## 1. National & International Highlights\n"
            "- Major bilateral agreements and summits concluded.\n"
            "- Key policy developments announced by international organizations.\n\n"
            "## 2. Economy & Technology\n"
            "- Innovation initiatives and economic growth projections.\n"
            "- Strategic investments in green energy and artificial intelligence.\n"
        )
    else:
        try:
            generated_text = generate_content_with_gemini(prompt, gemini_key)
        except Exception as e:
            logger.error(f"Gemini content generation failed: {e}")
            write_github_summary("❌ Gemini Generation Failed", [
                f"**Target Period**: {month_year_str}",
                f"**Error**: {e}"
            ])
            sys.exit(1)

    pdf_filename = f"Gemini_Current_Affairs_{month_year_str.replace(' ', '_')}.pdf"
    title_banner = f"Monthly Current Affairs Digest - {month_year_str}"

    try:
        pdf_bytes = create_pdf_from_text(generated_text, title_banner)
    except Exception as e:
        logger.error(f"PDF creation failed: {e}")
        write_github_summary("❌ PDF Creation Failed", [
            f"**Target Period**: {month_year_str}",
            f"**Error**: {e}"
        ])
        sys.exit(1)

    if args.output_pdf:
        try:
            with open(args.output_pdf, "wb") as f:
                f.write(pdf_bytes)
            logger.info(f"Saved generated PDF locally to '{args.output_pdf}'")
        except Exception as e:
            logger.warning(f"Could not save local PDF file: {e}")

    send_email(pdf_bytes, month_year_str, pdf_filename, args.dry_run)

    if not args.dry_run:
        mark_as_sent(month_year_str)
        write_github_summary("📧 Gemini Email Sent Successfully", [
            f"**Target Period**: {month_year_str}",
            f"**Attachment**: `{pdf_filename}` ({len(pdf_bytes)/(1024*1024):.2f} MB)",
            "**Provider**: Google Gemini API"
        ])
    else:
        write_github_summary("🧪 Dry Run Executed", [
            f"**Target Period**: {month_year_str}",
            f"**Attachment**: `{pdf_filename}` ({len(pdf_bytes)/(1024*1024):.2f} MB)",
            "**Note**: Dry run mode - no email sent."
        ])


if __name__ == "__main__":
    main()
