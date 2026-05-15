"""
One-shot script: inserts a pending test batch with 5 existing transactions.
Run once to get data for testing the review UI features.

Usage (venv active, from repo root):
    python loader/seed_test_batch.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import db

SAMPLE_PREDICTIONS = [
    ("Food", "Eating Out", "expense", 0.91, "ml"),
    ("Transport", "Cab", "expense", 0.85, "rule"),
    ("Shopping", "Groceries", "expense", 0.78, "ml"),
    ("Entertainment", "Movies", "expense", 0.60, "ml"),
    ("Utilities", "Electricity", "expense", 0.95, "memory"),
]

conn = db.get_connection()
try:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM transactions ORDER BY id DESC LIMIT 5"
        )
        txn_ids = [r[0] for r in cur.fetchall()]

    if not txn_ids:
        print("No transactions found — run the Gmail poller first.")
        sys.exit(1)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO transaction_batches (row_count) VALUES (%s) RETURNING id",
            (len(txn_ids),),
        )
        batch_id = cur.fetchone()[0]

    with conn.cursor() as cur:
        for txn_id, (cat, sub, typ, conf, src) in zip(txn_ids, SAMPLE_PREDICTIONS):
            cur.execute(
                """
                INSERT INTO transaction_batch_items
                    (batch_id, transaction_id,
                     pred_category, pred_subcategory, pred_type, pred_confidence, pred_source,
                     category, subcategory, type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (batch_id, txn_id, cat, sub, typ, conf, src, cat, sub, typ),
            )
    conn.commit()
    print(f"Test batch #{batch_id} created with {len(txn_ids)} items.")
finally:
    conn.close()
