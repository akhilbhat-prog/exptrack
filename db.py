"""
PostgreSQL helpers for the HDFC statement loader.

Tables managed here:
  transactions    — one row per parsed bank transaction
  processed_emails — idempotency log; every Gmail message ID lands here
"""

import os
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def get_connection():
    """Return a new psycopg2 connection using the DATABASE_URL env var."""
    url = os.environ["DATABASE_URL"]
    return psycopg2.connect(url)


def create_tables(conn) -> None:
    """Create transactions and processed_emails tables if they don't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id               SERIAL PRIMARY KEY,
                date             TIMESTAMPTZ,
                amount           NUMERIC(12, 2),
                type             VARCHAR(6),
                format           VARCHAR(20),
                account_last4    CHAR(4),
                card_last4       CHAR(4),
                vpa              TEXT,
                merchant         TEXT,
                upi_ref          VARCHAR(30),
                gmail_message_id TEXT UNIQUE,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS processed_emails (
                gmail_message_id TEXT PRIMARY KEY,
                processed_at     TIMESTAMPTZ,
                status           VARCHAR(10),
                notes            TEXT
            );
        """)
    conn.commit()
    logger.debug("Tables verified / created.")


def is_already_processed(conn, gmail_message_id: str) -> bool:
    """Return True if this Gmail message ID has already been processed."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM processed_emails WHERE gmail_message_id = %s",
            (gmail_message_id,),
        )
        return cur.fetchone() is not None


def insert_transaction(conn, transaction_dict: dict, gmail_message_id: str) -> None:
    """
    Insert a parsed transaction.  Silently ignores duplicate gmail_message_id
    so the function is safe to call more than once for the same message.
    """
    params = {**transaction_dict, "gmail_message_id": gmail_message_id}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO transactions
                (date, amount, type, format, account_last4, card_last4,
                 vpa, merchant, upi_ref, gmail_message_id)
            VALUES
                (%(date)s, %(amount)s, %(type)s, %(format)s, %(account_last4)s,
                 %(card_last4)s, %(vpa)s, %(merchant)s, %(upi_ref)s,
                 %(gmail_message_id)s)
            ON CONFLICT (gmail_message_id) DO NOTHING
            """,
            params,
        )
    conn.commit()
    logger.debug("Inserted transaction for message %s.", gmail_message_id)


def log_email(conn, gmail_message_id: str, status: str, notes: str | None = None) -> None:
    """
    Upsert a row in processed_emails.

    status must be one of: 'success', 'skipped', 'failed'
    """
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO processed_emails (gmail_message_id, processed_at, status, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (gmail_message_id) DO UPDATE
                SET processed_at = EXCLUDED.processed_at,
                    status       = EXCLUDED.status,
                    notes        = EXCLUDED.notes
            """,
            (gmail_message_id, now, status, notes),
        )
    conn.commit()
    logger.debug("Logged email %s as '%s'.", gmail_message_id, status)
