"""
One-time schema migration: adds financial analysis columns to
transaction_batch_items and data_feed_history.

Safe to re-run — all statements use ADD COLUMN IF NOT EXISTS.

Usage (from repo root):
    python loader/migrate.py
"""

import os
import sys

from dotenv import load_dotenv
import psycopg2

load_dotenv()

_MIGRATIONS = [
    # transaction_batch_items
    "ALTER TABLE transaction_batch_items ADD COLUMN IF NOT EXISTS cadence VARCHAR(20) DEFAULT 'O'",
    "ALTER TABLE transaction_batch_items ADD COLUMN IF NOT EXISTS divide_by INTEGER DEFAULT 1",
    "ALTER TABLE transaction_batch_items ADD COLUMN IF NOT EXISTS shared_expense CHAR(1) DEFAULT 'N'",
    "ALTER TABLE transaction_batch_items ADD COLUMN IF NOT EXISTS share_ratio NUMERIC(6,4) DEFAULT 1.0",
    # data_feed_history
    "ALTER TABLE data_feed_history ADD COLUMN IF NOT EXISTS time_period VARCHAR(10)",
    "ALTER TABLE data_feed_history ADD COLUMN IF NOT EXISTS cadence VARCHAR(20) DEFAULT 'O'",
    "ALTER TABLE data_feed_history ADD COLUMN IF NOT EXISTS divide_by INTEGER DEFAULT 1",
    "ALTER TABLE data_feed_history ADD COLUMN IF NOT EXISTS monthly_amount NUMERIC(12,2)",
    "ALTER TABLE data_feed_history ADD COLUMN IF NOT EXISTS shared_expense CHAR(1) DEFAULT 'N'",
    "ALTER TABLE data_feed_history ADD COLUMN IF NOT EXISTS share_ratio NUMERIC(6,4) DEFAULT 1.0",
    "ALTER TABLE data_feed_history ADD COLUMN IF NOT EXISTS final_amount NUMERIC(12,2)",
]


def run():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            for sql in _MIGRATIONS:
                cur.execute(sql)
                print(f"  OK  {sql[:80]}")
        conn.commit()
        print(f"\nMigration complete — {len(_MIGRATIONS)} statement(s) applied.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
