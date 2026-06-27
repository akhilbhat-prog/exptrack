"""
Gmail poller — bank email polling and parsing pipeline.

Reads HDFC Bank alert emails from Gmail, parses them with parser.py,
and persists the results to a Neon PostgreSQL database via db.py.

Run directly for CLI mode (no Flask server):
    python loader/gmail_poller.py

For the Cloud Run HTTP server, see loader/app.py.
Authentication uses OAuth2 refresh-token flow; credentials are read
exclusively from environment variables (no token.json / credentials.json).
"""

import base64
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from html.parser import HTMLParser

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

import db
import parser as email_parser

# Make categorizer/ importable without modifying sys.path globally elsewhere.
# __file__ is loader/gmail_poller.py so we go up one level to reach the project root.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_project_root, "categorizer"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
HDFC_SENDERS = ["alerts@hdfcbank.bank.in", "alerts@hdfcbank.net"]
IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Gmail API helpers
# ---------------------------------------------------------------------------

def _build_gmail_service():
    """Construct a Gmail API service using OAuth2 refresh-token credentials."""
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=creds)


def _list_messages(service, query: str) -> list[dict]:
    """Return all message stubs matching *query*, handling pagination."""
    messages: list[dict] = []
    kwargs: dict = {"userId": "me", "q": query}

    while True:
        result = service.users().messages().list(**kwargs).execute()
        messages.extend(result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
        kwargs["pageToken"] = page_token

    return messages


class _TextExtractor(HTMLParser):
    _SKIP_TAGS  = {"style", "script", "head"}
    _BLOCK_TAGS = {"br", "p", "div", "tr", "td", "li",
                   "h1", "h2", "h3", "h4", "h5", "h6", "hr"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS and not self._skip_depth:
            self._parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        return re.sub(r"[ \t\r\n ]+", " ", text).strip()


def _strip_html(html: str) -> str:
    import html as html_mod
    extractor = _TextExtractor()
    extractor.feed(html_mod.unescape(html))
    return extractor.get_text()


def _get_subject(msg: dict) -> str:
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == "subject":
            return h.get("value", "")
    return "(no subject)"


def _extract_raw_html(payload: dict, service=None, msg_id: str = "") -> str:
    """Return raw (un-stripped) text/html content for diagnostic logging."""
    if payload.get("mimeType") == "text/html":
        data = _get_body_data(service, msg_id, payload) if service else payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _extract_raw_html(part, service, msg_id)
        if result:
            return result
    return ""


def _extract_plain(payload: dict, service=None, msg_id: str = "") -> str:
    """Return the first text/plain body found, recursively."""
    if payload.get("mimeType") == "text/plain":
        data = _get_body_data(service, msg_id, payload) if service else payload.get("body", {}).get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return re.sub(r"<https?://\S+>", "", text)
    for part in payload.get("parts", []):
        result = _extract_plain(part, service, msg_id)
        if result:
            return result
    return ""


def _extract_html(payload: dict, service=None, msg_id: str = "") -> str:
    """Return the first text/html body found (tags stripped), recursively."""
    if payload.get("mimeType") == "text/html":
        data = _get_body_data(service, msg_id, payload) if service else payload.get("body", {}).get("data", "")
        if data:
            raw = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return _strip_html(raw)
    for part in payload.get("parts", []):
        result = _extract_html(part, service, msg_id)
        if result:
            return result
    return ""


def _get_received_at(msg: dict) -> datetime:
    """
    Return email receive time as a UTC datetime.

    Uses Gmail's internalDate field (milliseconds since epoch, always UTC)
    rather than the Date header, which can be malformed or in various
    timezone formats.
    """
    internal_ms = int(msg.get("internalDate", 0))
    if internal_ms:
        return datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)
    # Fallback: should never be reached for real Gmail messages.
    logger.warning("internalDate missing; using current time as received_at.")
    return datetime.now(timezone.utc)


def _log_mime_tree(payload: dict, depth: int = 0) -> None:
    """Log the MIME part tree at WARNING level for diagnosing empty-body messages."""
    indent = "  " * depth
    mime = payload.get("mimeType", "?")
    body = payload.get("body", {})
    size = body.get("size", 0)
    has_data = bool(body.get("data"))
    has_att_id = bool(body.get("attachmentId"))
    logger.warning(
        "%s[%s]  size=%d  inline_data=%s  attachmentId=%s",
        indent, mime, size, has_data, has_att_id,
    )
    for part in payload.get("parts", []):
        _log_mime_tree(part, depth + 1)


def _get_body_data(service, msg_id: str, part: dict) -> str:
    """Return the raw base64url body data for a MIME part.

    Gmail omits the inline ``data`` field and supplies an ``attachmentId``
    when the body exceeds ~2 MB. This helper fetches it transparently.
    """
    body = part.get("body", {})
    data = body.get("data", "")
    if data:
        return data
    att_id = body.get("attachmentId")
    if att_id:
        att = service.users().messages().attachments().get(
            userId="me", messageId=msg_id, id=att_id
        ).execute()
        return att.get("data", "")
    return ""


# ---------------------------------------------------------------------------
# Parser test runner
# ---------------------------------------------------------------------------

def run_parser_tests() -> str:
    """Run parser.py unit tests and return the captured output."""
    result = subprocess.run(
        [sys.executable, "parser.py"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    return (result.stdout + result.stderr).strip()


# ---------------------------------------------------------------------------
# Summary email
# ---------------------------------------------------------------------------

def send_summary_email(service, summary: dict, test_output: str, categorization_status: str = "ok") -> None:
    recipient = os.environ.get("NOTIFICATION_EMAIL", "")
    if not recipient:
        logger.warning("NOTIFICATION_EMAIL not set — skipping summary email.")
        return

    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%d %b %Y")
    no_transactions = summary["processed"] == 0 and summary["skipped"] == 0

    subject = (
        f"ExpTrack Pipeline Run – No Transactions | {date_str}"
        if no_transactions
        else f"ExpTrack Pipeline Run – {date_str}"
    )

    lines = [
        f"ExpTrack Pipeline Run — {date_str}",
        "",
        "Run Summary",
        "-" * 40,
        f"Processed : {summary['processed']}",
        f"Skipped   : {summary['skipped']}",
        f"Failed    : {summary['failed']}",
        "",
    ]

    if no_transactions:
        lines.append("No new transactions were found in this run.")
    else:
        lines += ["Transactions Processed", "-" * 40]
        for i, t in enumerate(summary["transactions"], 1):
            date_ist = t["date"].astimezone(IST)
            lines.append(
                f"{i}. {t['format'].upper():<12} {t['type']:<7} "
                f"Rs. {t['amount']:>10,.2f}   {t['merchant']:<30}  "
                f"{date_ist.strftime('%d %b %Y %H:%M IST')}"
            )

    failed_details = summary.get("failed_details", [])
    skipped_details = summary.get("skipped_details", [])

    if failed_details:
        lines += ["", f"Failed Messages ({len(failed_details)})", "-" * 40]
        for i, entry in enumerate(failed_details, 1):
            snippet = f"  ({entry['snippet']})" if entry.get("snippet") else ""
            lines.append(f"{i}. id={entry['id']}  {entry['reason']}{snippet}")

    if skipped_details:
        lines += ["", f"Skipped Messages ({len(skipped_details)})", "-" * 40]
        for i, entry in enumerate(skipped_details, 1):
            detail = ""
            if entry.get("merchant"):
                detail = f"  ({entry['merchant']}  Rs. {entry['amount']:,.2f}  {entry['txn_type']})"
            lines.append(f"{i}. id={entry['id']}  {entry['reason']}{detail}")

    lines += [
        "",
        "Categorization",
        "-" * 40,
        categorization_status,
        "",
        "Parser Test Results",
        "-" * 40,
        test_output or "(no output)",
    ]

    msg = MIMEText("\n".join(lines))
    msg["to"] = recipient
    msg["from"] = "me"
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    logger.info("Summary email sent to %s", recipient)


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

def main(service) -> dict:
    sender_filter = " OR ".join(f"from:{s}" for s in HDFC_SENDERS)
    after_date = os.environ.get("AFTER_DATE")  # YYYY/MM/DD — exclusive, so use day before desired start
    if after_date:
        query = f'{{{sender_filter}}} after:{after_date}'
    else:
        poll_days = int(os.environ.get("POLL_DAYS", "1"))
        query = f'{{{sender_filter}}} newer_than:{poll_days}d'

    logger.info("Connecting to database …")
    conn = db.get_connection()
    db.create_tables(conn)

    logger.info("Gmail query: %s", query)
    message_stubs = _list_messages(service, query)
    logger.info("Found %d message(s).", len(message_stubs))

    max_messages = int(os.environ.get("MAX_MESSAGES", "0"))
    if max_messages:
        message_stubs = message_stubs[:max_messages]
        logger.info("Capped to %d message(s) via MAX_MESSAGES.", len(message_stubs))

    if not message_stubs:
        conn.close()
        return {"processed": 0, "skipped": 0, "failed": 0, "transactions": [],
                "failed_details": [], "skipped_details": []}

    processed = skipped = failed = 0
    transactions: list[dict] = []
    failed_details: list[dict] = []
    skipped_details: list[dict] = []

    for stub in message_stubs:
        gmail_message_id = stub["id"]
        try:
            # --- Idempotency check ---
            if db.is_already_processed(conn, gmail_message_id):
                logger.warning(
                    "Message %s already in processed_emails — skipping.", gmail_message_id
                )
                entry = {"id": gmail_message_id, "reason": "already processed"}
                txn = db.get_transaction_by_message_id(conn, gmail_message_id)
                if txn:
                    entry["merchant"] = txn["merchant"]
                    entry["amount"]   = txn["amount"]
                    entry["txn_type"] = txn["type"]
                skipped_details.append(entry)
                skipped += 1
                continue

            # --- Fetch full message ---
            msg = service.users().messages().get(
                userId="me", id=gmail_message_id, format="full"
            ).execute()

            received_at = _get_received_at(msg)
            payload = msg.get("payload", {})
            plain_body = _extract_plain(payload, service, gmail_message_id)
            transaction = email_parser.parse(plain_body, received_at) if plain_body.strip() else None

            html_body = ""
            if transaction is None:
                html_body = _extract_html(payload, service, gmail_message_id)
                transaction = email_parser.parse(html_body, received_at) if html_body.strip() else None

            logger.debug(
                "msg=%s  plain=%d chars  html=%d chars",
                gmail_message_id, len(plain_body), len(html_body),
            )

            body = (plain_body or html_body).strip()

            if not body:
                subject = _get_subject(msg)
                logger.error(
                    "Empty body for message %s (subject: %s) — MIME tree:",
                    gmail_message_id, subject,
                )
                _log_mime_tree(payload)
                raw_html = _extract_raw_html(payload, service, gmail_message_id) or plain_body
                if raw_html:
                    logger.warning("Full email body for message %s:\n%s", gmail_message_id, raw_html)
                db.log_email(conn, gmail_message_id, "failed", "empty body")
                failed_details.append({"id": gmail_message_id, "reason": "empty body"})
                failed += 1
                continue

            if transaction is None:
                logger.error(
                    "Unrecognised format for message %s. Body snippet: %.200s",
                    gmail_message_id,
                    body.replace("\n", " "),
                )
                db.log_email(conn, gmail_message_id, "failed", "unrecognised format")
                failed_details.append({
                    "id": gmail_message_id,
                    "reason": "unrecognised format",
                    "snippet": body[:100].replace("\n", " "),
                })
                failed += 1
                continue

            # --- Duplicate transaction check ---
            existing_id = db.find_duplicate_transaction(conn, transaction)
            if existing_id:
                logger.warning(
                    "Duplicate transaction in msg %s — already stored under msg %s. Skipping.",
                    gmail_message_id, existing_id,
                )
                db.log_email(conn, gmail_message_id, "skipped", f"duplicate of {existing_id}")
                skipped_details.append({"id": gmail_message_id, "reason": f"duplicate of {existing_id}"})
                skipped += 1
                continue

            # --- Persist ---
            db.insert_transaction(conn, transaction, gmail_message_id)
            db.log_email(conn, gmail_message_id, "success")
            logger.info(
                "Saved  %s  %s  %.2f  merchant=%s  msg=%s",
                transaction["format"],
                transaction["type"],
                transaction["amount"],
                transaction["merchant"],
                gmail_message_id,
            )
            transactions.append(transaction)
            processed += 1

        except Exception as exc:
            logger.exception("Unexpected error processing message %s.", gmail_message_id)
            try:
                db.log_email(conn, gmail_message_id, "failed", "unexpected error")
            except Exception:
                pass
            failed_details.append({
                "id": gmail_message_id,
                "reason": f"unexpected error: {type(exc).__name__}: {exc}",
            })
            failed += 1

    conn.close()
    return {
        "processed": processed, "skipped": skipped, "failed": failed,
        "transactions": transactions,
        "failed_details": failed_details,
        "skipped_details": skipped_details,
    }


# ---------------------------------------------------------------------------
# Categorization (spend-tracker integration)
# ---------------------------------------------------------------------------

def run_categorization() -> str:
    """Run the spend-tracker batch classification on any unprocessed transactions.

    Imported lazily so a missing/broken categorizer never crashes the email loader.
    Returns "ok" on success or a "FAILED: <reason>" string on error.
    """
    try:
        _cat_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "categorizer")
        if _cat_dir not in sys.path:
            sys.path.insert(0, _cat_dir)
        from batch_process import cmd_process
        cmd_process()
        return "ok"
    except Exception as exc:
        logger.exception("Categorization batch failed — email loading was successful.")
        return f"FAILED: {exc}"


# ---------------------------------------------------------------------------
# Entry point (CLI mode)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    svc = _build_gmail_service()
    summary = main(svc)
    cat_status = run_categorization()
    test_output = run_parser_tests()
    send_summary_email(svc, summary, test_output, categorization_status=cat_status)
    print(
        f"Summary: {summary['processed']} processed, "
        f"{summary['skipped']} skipped, {summary['failed']} failed"
    )
