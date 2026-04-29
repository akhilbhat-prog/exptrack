"""
Gmail poller — main entry point for the HDFC statement loader.

Reads HDFC Bank alert emails from Gmail, parses them with parser.py,
and persists the results to a Neon PostgreSQL database via db.py.

Authentication uses OAuth2 refresh-token flow; credentials are read
exclusively from environment variables (no token.json / credentials.json).
"""

import base64
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

import db
import parser as email_parser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
HDFC_SENDER = "alerts@hdfcbank.net"


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


def _extract_body(payload: dict) -> str:
    """
    Recursively walk a Gmail message payload and return the first
    non-empty plain-text part.
    """
    mime = payload.get("mimeType", "")

    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        body = _extract_body(part)
        if body:
            return body

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


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

def main() -> None:
    poll_days = int(os.environ.get("POLL_DAYS", "1"))
    query = f"label:inbox from:{HDFC_SENDER} newer_than:{poll_days}d"

    logger.info("Connecting to database …")
    conn = db.get_connection()
    db.create_tables(conn)

    logger.info("Authenticating with Gmail API …")
    service = _build_gmail_service()

    logger.info("Gmail query: %s", query)
    message_stubs = _list_messages(service, query)
    logger.info("Found %d message(s).", len(message_stubs))

    if not message_stubs:
        print("Summary: 0 processed, 0 skipped, 0 failed")
        conn.close()
        return

    processed = skipped = failed = 0

    for stub in message_stubs:
        gmail_message_id = stub["id"]
        try:
            # --- Idempotency check ---
            if db.is_already_processed(conn, gmail_message_id):
                logger.warning(
                    "Message %s already in processed_emails — skipping.", gmail_message_id
                )
                skipped += 1
                continue

            # --- Fetch full message ---
            msg = service.users().messages().get(
                userId="me", id=gmail_message_id, format="full"
            ).execute()

            received_at = _get_received_at(msg)
            body = _extract_body(msg.get("payload", {}))

            if not body:
                logger.error("Empty body for message %s.", gmail_message_id)
                db.log_email(conn, gmail_message_id, "failed", "empty body")
                failed += 1
                continue

            # --- Parse ---
            transaction = email_parser.parse(body, received_at)

            if transaction is None:
                logger.error(
                    "Unrecognised format for message %s. Body snippet: %.120s",
                    gmail_message_id,
                    body.replace("\n", " "),
                )
                db.log_email(conn, gmail_message_id, "failed", "unrecognised format")
                failed += 1
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
            processed += 1

        except Exception:
            logger.exception("Unexpected error processing message %s.", gmail_message_id)
            try:
                # Best-effort — the connection might itself be broken.
                db.log_email(conn, gmail_message_id, "failed", "unexpected error")
            except Exception:
                pass
            failed += 1

    conn.close()
    print(f"Summary: {processed} processed, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
