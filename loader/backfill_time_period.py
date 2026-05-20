"""
One-shot: backfill time_period from entry_date for all data_feed_history rows
where time_period is NULL or empty.

Run once from the loader/ directory:
    python backfill_time_period.py
"""

from dotenv import load_dotenv
import db

load_dotenv()

conn = db.get_connection()
try:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE data_feed_history
               SET time_period = TO_CHAR(entry_date, 'Mon-YYYY')
             WHERE (time_period IS NULL OR TRIM(time_period) = '')
               AND entry_date IS NOT NULL
        """)
        print(f"Updated {cur.rowcount} rows.")
    conn.commit()
finally:
    conn.close()
