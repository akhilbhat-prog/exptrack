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

            ALTER TABLE IF EXISTS transaction_batch_items ADD COLUMN IF NOT EXISTS cadence VARCHAR(20) DEFAULT 'O';
            ALTER TABLE IF EXISTS transaction_batch_items ADD COLUMN IF NOT EXISTS divide_by INTEGER DEFAULT 1;
            ALTER TABLE IF EXISTS transaction_batch_items ADD COLUMN IF NOT EXISTS shared_expense CHAR(1) DEFAULT 'N';
            ALTER TABLE IF EXISTS transaction_batch_items ADD COLUMN IF NOT EXISTS share_ratio NUMERIC(6,4) DEFAULT 1.0;
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

            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS time_period VARCHAR(10);
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS cadence VARCHAR(20) DEFAULT 'O';
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS divide_by INTEGER DEFAULT 1;
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS monthly_amount NUMERIC(12,2);
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS shared_expense CHAR(1) DEFAULT 'N';
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS share_ratio NUMERIC(6,4) DEFAULT 1.0;
            ALTER TABLE IF EXISTS data_feed_history ADD COLUMN IF NOT EXISTS final_amount NUMERIC(12,2);
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
    time_period: str | None = None,
    cadence: str | None = "O",
    divide_by: int = 1,
    monthly_amount=None,
    shared_expense: str | None = "N",
    share_ratio=None,
    final_amount=None,
) -> bool:
    """Insert one row into data_feed_history. Returns True on success."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_feed_history
                (entry_date, entry_text, sub_category, category, spend_type,
                 amount, merchant, vpa, upi_ref,
                 time_period, cadence, divide_by, monthly_amount,
                 shared_expense, share_ratio, final_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (entry_date, entry_text, sub_category, category, spend_type,
             amount, merchant, vpa, upi_ref,
             time_period, cadence, divide_by, monthly_amount,
             shared_expense, share_ratio, final_amount),
        )
    conn.commit()
    return True


def get_history_periods(conn) -> list[dict]:
    """Return [{period, count}, ...] sorted newest-first by calendar month.

    Derives period from entry_date for rows where time_period is unset.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY')) AS period,
                COUNT(*) AS cnt
            FROM data_feed_history
            WHERE entry_date IS NOT NULL
            GROUP BY COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY'))
            ORDER BY TO_DATE(
                COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY')),
                'Mon-YYYY'
            ) DESC
        """)
        rows = cur.fetchall()
    return [{"period": r[0], "count": r[1]} for r in rows]


def get_history_page(conn, period: str, page: int, page_size: int = 25) -> dict:
    """Return {items, total, page, pages} for one time_period page."""
    offset = (page - 1) * page_size
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM data_feed_history
               WHERE COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY')) = %s""",
            (period,),
        )
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT id, entry_date, time_period, merchant, entry_text, amount,
                   category, sub_category, spend_type,
                   cadence, divide_by, monthly_amount,
                   shared_expense, share_ratio, final_amount
            FROM data_feed_history
            WHERE COALESCE(NULLIF(TRIM(time_period), ''), TO_CHAR(entry_date, 'Mon-YYYY')) = %s
            ORDER BY entry_date ASC, id ASC
            LIMIT %s OFFSET %s
        """, (period, page_size, offset))
        rows = cur.fetchall()
    items = [
        {
            "id":             r[0],
            "date":           r[1].isoformat() if r[1] else None,
            "time_period":    r[2],
            "merchant":       r[3],
            "entry_text":     r[4],
            "amount":         float(r[5]) if r[5] is not None else None,
            "category":       r[6] or "",
            "sub_category":   r[7] or "",
            "spend_type":     r[8] or "",
            "cadence":        r[9] if r[9] is not None else "O",
            "divide_by":      r[10] if r[10] is not None else 1,
            "monthly_amount": float(r[11]) if r[11] is not None else None,
            "shared_expense": r[12] if r[12] is not None else "N",
            "share_ratio":    float(r[13]) if r[13] is not None else 1.0,
            "final_amount":   float(r[14]) if r[14] is not None else None,
        }
        for r in rows
    ]
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": items, "total": total, "page": page, "pages": pages}


def update_history_row(conn, row_id: int, fields: dict) -> dict | None:
    """Update editable fields of a data_feed_history row. Returns computed amounts or None if not found."""
    with conn.cursor() as cur:
        cur.execute("SELECT amount FROM data_feed_history WHERE id = %s", (row_id,))
        row = cur.fetchone()
        if not row:
            return None
        amount = float(row[0]) if row[0] is not None else 0.0
        divide_by = max(1, int(fields.get("divide_by") or 1))
        share_ratio = float(fields.get("share_ratio") or 1.0)
        monthly_amount = round(amount / divide_by, 2)
        final_amount = round(monthly_amount * share_ratio, 2)
        cur.execute("""
            UPDATE data_feed_history
               SET time_period    = %s,
                   category       = %s,
                   sub_category   = %s,
                   spend_type     = %s,
                   cadence        = %s,
                   divide_by      = %s,
                   shared_expense = %s,
                   share_ratio    = %s,
                   monthly_amount = %s,
                   final_amount   = %s
             WHERE id = %s
        """, (
            fields.get("time_period"),
            fields.get("category") or None,
            fields.get("sub_category") or None,
            fields.get("spend_type") or None,
            fields.get("cadence") or "O",
            divide_by,
            fields.get("shared_expense") or "N",
            share_ratio,
            monthly_amount,
            final_amount,
            row_id,
        ))
        if cur.rowcount == 0:
            return None
    conn.commit()
    return {"monthly_amount": monthly_amount, "final_amount": final_amount}


def delete_history_row(conn, row_id: int) -> bool:
    """Delete a data_feed_history row by id. Returns True if a row was deleted."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM data_feed_history WHERE id = %s", (row_id,))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def get_history_summary(conn, period: str, prev_period: str | None = None) -> dict:
    """Return top-5 categories by spend for a time period, plus the period grand total.

    When prev_period is supplied each category also includes prev_total (the same
    category's spend in that period, or None if absent).
    """
    with conn.cursor() as cur:
        if prev_period:
            cur.execute(
                """
                SELECT
                    cat,
                    SUM(CASE WHEN period_key = %(cur)s  THEN amt END)  AS cur_total,
                    SUM(CASE WHEN period_key = %(prev)s THEN amt END)  AS prev_total,
                    COUNT(CASE WHEN period_key = %(cur)s THEN 1 END)   AS cnt,
                    SUM(SUM(CASE WHEN period_key = %(cur)s THEN amt END)) OVER () AS period_total
                FROM (
                    SELECT
                        COALESCE(NULLIF(TRIM(category), ''), 'Uncategorised') AS cat,
                        COALESCE(NULLIF(TRIM(time_period), ''),
                                 TO_CHAR(entry_date, 'Mon-YYYY'))             AS period_key,
                        COALESCE(final_amount, amount)                        AS amt
                    FROM data_feed_history
                    WHERE COALESCE(NULLIF(TRIM(time_period), ''),
                                   TO_CHAR(entry_date, 'Mon-YYYY')) IN (%(cur)s, %(prev)s)
                ) sub
                GROUP BY cat
                HAVING COUNT(CASE WHEN period_key = %(cur)s THEN 1 END) > 0
                ORDER BY cur_total DESC NULLS LAST
                LIMIT 5
                """,
                {"cur": period, "prev": prev_period},
            )
            rows = cur.fetchall()
            period_total = float(rows[0][4]) if rows and rows[0][4] is not None else 0.0
            return {
                "top_categories": [
                    {
                        "category":   r[0],
                        "total":      float(r[1]) if r[1] is not None else 0.0,
                        "prev_total": float(r[2]) if r[2] is not None else None,
                        "count":      r[3],
                    }
                    for r in rows
                ],
                "period_total": period_total,
            }
        else:
            cur.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(category), ''), 'Uncategorised') AS category,
                    SUM(COALESCE(final_amount, amount))                   AS total,
                    COUNT(*)                                              AS cnt,
                    SUM(SUM(COALESCE(final_amount, amount))) OVER ()      AS period_total
                FROM data_feed_history
                WHERE COALESCE(NULLIF(TRIM(time_period), ''),
                               TO_CHAR(entry_date, 'Mon-YYYY')) = %s
                GROUP BY COALESCE(NULLIF(TRIM(category), ''), 'Uncategorised')
                ORDER BY SUM(COALESCE(final_amount, amount)) DESC
                LIMIT 5
                """,
                (period,),
            )
            rows = cur.fetchall()
            period_total = float(rows[0][3]) if rows and rows[0][3] is not None else 0.0
            return {
                "top_categories": [
                    {"category": r[0], "total": float(r[1]) if r[1] is not None else 0.0, "count": r[2]}
                    for r in rows
                ],
                "period_total": period_total,
            }


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
