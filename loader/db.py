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
                raw_entry        TEXT,
                upi_ref          VARCHAR(30),
                gmail_message_id TEXT UNIQUE,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE transactions ADD COLUMN IF NOT EXISTS raw_entry TEXT;

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
                 vpa, merchant, raw_entry, upi_ref, gmail_message_id)
            VALUES
                (%(date)s, %(amount)s, %(type)s, %(format)s, %(account_last4)s,
                 %(card_last4)s, %(vpa)s, %(merchant)s, %(raw_entry)s,
                 %(upi_ref)s, %(gmail_message_id)s)
            ON CONFLICT (gmail_message_id) DO NOTHING
            """,
            params,
        )
    conn.commit()
    logger.debug("Inserted transaction for message %s.", gmail_message_id)


def create_data_feed_table(conn) -> None:
    """Create the data_feed_history table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS data_feed_history (
                id           SERIAL PRIMARY KEY,
                entry_date   DATE NOT NULL,
                entry_text   TEXT NOT NULL,
                sub_category TEXT,
                category     TEXT,
                spend_type   VARCHAR(20),
                amount       NUMERIC(12, 2) NOT NULL,
                merchant     TEXT,
                vpa          TEXT,
                upi_ref      TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    conn.commit()


def insert_data_feed_row(
    conn,
    entry_date,
    entry_text: str,
    sub_category: str | None,
    category: str | None,
    spend_type: str | None,
    amount,
    merchant: str | None = None,
    vpa: str | None = None,
    upi_ref: str | None = None,
) -> bool:
    """Insert one row into data_feed_history. Returns True on success."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_feed_history
                (entry_date, entry_text, sub_category, category, spend_type,
                 amount, merchant, vpa, upi_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (entry_date, entry_text, sub_category, category, spend_type,
             amount, merchant, vpa, upi_ref),
        )
    conn.commit()
    return True


def find_duplicate_transaction(conn, transaction: dict) -> str | None:
    """
    Return the gmail_message_id of an existing transaction that matches the
    given parsed transaction, or None if no duplicate exists.

    UPI transactions match on upi_ref.
    All other formats match on (amount, date, format, merchant).
    """
    with conn.cursor() as cur:
        if transaction.get("upi_ref"):
            cur.execute(
                "SELECT gmail_message_id FROM transactions WHERE upi_ref = %s",
                (transaction["upi_ref"],),
            )
        else:
            cur.execute(
                """
                SELECT gmail_message_id FROM transactions
                WHERE amount = %s AND date = %s AND format = %s AND merchant = %s
                """,
                (transaction["amount"], transaction["date"],
                 transaction["format"], transaction["merchant"]),
            )
        row = cur.fetchone()
        return row[0] if row else None


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
