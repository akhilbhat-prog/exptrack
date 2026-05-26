from __future__ import annotations

import pandas as pd
import psycopg

from ingestion.database import connect, insert_data_feed_history


_FETCH_QUERY = """
SELECT
    t.id          AS id,
    t.date        AS date,
    t.raw_entry   AS entry_raw,
    t.amount      AS amount,
    t.merchant    AS db_merchant,
    t.vpa         AS vpa,
    t.upi_ref     AS upi_ref
FROM public.transactions t
WHERE t.id NOT IN (
    SELECT transaction_id FROM public.transaction_batch_items
)
AND t.id NOT IN (
    SELECT transaction_id FROM public.transaction_exclusions
)
ORDER BY t.date, t.id
"""

_FETCH_BATCH_ITEMS_QUERY = """
SELECT
    tbi.transaction_id,
    COALESCE(NULLIF(TRIM(tbi.category),    ''), tbi.pred_category)    AS category,
    COALESCE(NULLIF(TRIM(tbi.subcategory), ''), tbi.pred_subcategory) AS subcategory,
    COALESCE(NULLIF(TRIM(tbi.type),        ''), tbi.pred_type)        AS type,
    t.date,
    t.raw_entry,
    t.amount,
    t.merchant,
    t.vpa,
    t.upi_ref,
    tbi.cadence,
    tbi.divide_by,
    tbi.shared_expense,
    tbi.share_ratio
FROM public.transaction_batch_items tbi
JOIN public.transactions t ON t.id = tbi.transaction_id
WHERE tbi.batch_id = %s
"""


def fetch_transactions() -> pd.DataFrame:
    """
    Return all transactions not already in a completed batch,
    with columns mapped to the pipeline's internal schema.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_FETCH_QUERY)
            rows = cur.fetchall()
            cols = [d.name for d in cur.description]

    df = pd.DataFrame(rows, columns=cols)
    df["id"] = pd.to_numeric(df["id"], errors="coerce").astype("Int64")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    for col in ["entry_raw", "db_merchant", "vpa", "upi_ref"]:
        df[col] = df[col].fillna("").astype(str).str.strip()
    return df


def create_batch(conn: psycopg.Connection, row_count: int) -> int:
    """Insert a new pending batch record and return its id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.transaction_batches (row_count) VALUES (%s) RETURNING id",
            (row_count,),
        )
        batch_id = cur.fetchone()[0]
    conn.commit()
    return batch_id


def insert_batch_items(
    conn: psycopg.Connection, batch_id: int, processed_df: pd.DataFrame
) -> None:
    """
    Bulk-insert prediction results into transaction_batch_items.
    Both pred_* (immutable reference) and editable columns are pre-filled
    from the model's output.
    """
    sql = """
        INSERT INTO public.transaction_batch_items
            (batch_id, transaction_id,
             pred_category, pred_subcategory, pred_type, pred_confidence, pred_source,
             category, subcategory, type,
             cadence, divide_by, shared_expense, share_ratio)
        VALUES
            (%(batch_id)s, %(transaction_id)s,
             %(pred_category)s, %(pred_subcategory)s, %(pred_type)s,
             %(pred_confidence)s, %(pred_source)s,
             %(pred_category)s, %(pred_subcategory)s, %(pred_type)s,
             'O', 1, 'N', 1.0)
    """
    rows = [
        {
            "batch_id": batch_id,
            "transaction_id": int(row["id"]),
            "pred_category": row.get("pred_category", "Unknown"),
            "pred_subcategory": row.get("pred_subcategory", "Unknown"),
            "pred_type": row.get("pred_type", "Unknown"),
            "pred_confidence": (
                round(float(row["confidence"]), 4)
                if row.get("confidence") is not None
                else None
            ),
            "pred_source": row.get("prediction_source", "none"),
        }
        for _, row in processed_df.iterrows()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()


def complete_batch(conn: psycopg.Connection, batch_id: int) -> int:
    """
    Validate that the batch is reviewed, insert rows into data_feed_history
    (using editable values with pred_* fallback for blanks), mark batch complete.
    Returns the number of rows inserted.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM public.transaction_batches WHERE id = %s",
            (batch_id,),
        )
        result = cur.fetchone()

    if result is None:
        raise ValueError(f"Batch {batch_id} not found.")
    status = result[0]
    if status != "reviewed":
        raise ValueError(
            f"Batch {batch_id} has status '{status}'. "
            "Set status='reviewed' in transaction_batches before completing."
        )

    with conn.cursor() as cur:
        cur.execute(_FETCH_BATCH_ITEMS_QUERY, (batch_id,))
        items = cur.fetchall()
        cols = [d.name for d in cur.description]

    rows = []
    for item in items:
        r = dict(zip(cols, item))
        divide_by = r.get("divide_by") or 1
        share_ratio = float(r.get("share_ratio") or 1.0)
        amount_val = float(r["amount"]) if r.get("amount") is not None else 0.0
        monthly_amount = round(amount_val / divide_by, 2)
        final_amount = round(monthly_amount * share_ratio, 2)
        date = r["date"]
        rows.append(
            {
                "entry_date": date,
                "entry_text": r["raw_entry"],
                "amount": r["amount"],
                "category": r["category"],
                "sub_category": r["subcategory"],
                "spend_type": r["type"],
                "merchant": r["merchant"] or "",
                "vpa": r["vpa"] or "",
                "upi_ref": r["upi_ref"] or "",
                "time_period": date.strftime("%b-%Y") if date else None,
                "cadence": r.get("cadence") or "O",
                "divide_by": divide_by,
                "monthly_amount": monthly_amount,
                "shared_expense": r.get("shared_expense") or "N",
                "share_ratio": share_ratio,
                "final_amount": final_amount,
            }
        )

    insert_data_feed_history(conn, rows)

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE public.transaction_batches "
            "SET status = 'complete', completed_at = now() "
            "WHERE id = %s",
            (batch_id,),
        )
    conn.commit()

    return len(rows)
