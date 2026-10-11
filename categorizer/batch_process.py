from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ingestion.database import connect, parse_database
from ingestion.transactions import complete_batch, create_batch, fetch_transactions, insert_batch_items
from models.registry import load_model, model_updated_at, register_model
from models.train import train_category_model
from processing.cleaner import clean_entry
from processing.memory import MerchantMemory
from processing.pipeline import process_dataframe
from processing.rules import load_rules

DEFAULT_RULES_PATH = Path(__file__).parent / "config" / "rules.json"
BATCH_SIZE = 25


def cmd_process() -> None:
    print("Loading registered model...")
    model = load_model()

    rules = load_rules(DEFAULT_RULES_PATH)

    print("Fetching transactions...")
    transactions_df = fetch_transactions()
    if transactions_df.empty:
        print("No new transactions to process.")
        return

    memory = _load_memory()

    print(f"Running predictions on {len(transactions_df)} transactions...")
    processed_df = process_dataframe(transactions_df, rules=rules, memory=memory, model=model)

    chunks = [processed_df.iloc[i:i + BATCH_SIZE] for i in range(0, len(processed_df), BATCH_SIZE)]
    batch_ids = []
    with connect() as conn:
        for chunk in chunks:
            batch_id = create_batch(conn, row_count=len(chunk))
            insert_batch_items(conn, batch_id, chunk)
            batch_ids.append(batch_id)

    print(f"\n{len(batch_ids)} batch(es) created — {len(processed_df)} transactions total.")
    for bid in batch_ids:
        print(f"  Batch #{bid}")


def _load_memory() -> MerchantMemory:
    """Payee memory from labelled history; empty (ML takes over) if history can't be loaded."""
    try:
        memory = MerchantMemory.from_history(parse_database())
    except Exception as exc:
        print(f"Merchant memory unavailable, continuing without it: {exc}", file=sys.stderr)
        return MerchantMemory()
    print(f"Merchant memory: {len(memory.memory)} payees.")
    return memory


def cmd_complete(batch_id: int) -> None:
    print(f"Completing batch #{batch_id}...")
    with connect() as conn:
        try:
            inserted = complete_batch(conn, batch_id)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    print(f"Inserted {inserted} rows into data_feed_history.")

    print("\nRetraining model on updated history...")
    retrain()


def retrain() -> None:
    history_df = parse_database()
    history_df["entry_clean"] = history_df["entry_raw"].map(clean_entry)
    model = train_category_model(history_df)
    register_model(model)
    print("New model version registered as champion.")


def _latest_batch_completed_at():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(completed_at) FROM public.transaction_batches WHERE status = 'complete'"
            )
            return cur.fetchone()[0]


def retrain_if_stale() -> bool:
    """Retrain when a batch was completed after the champion was saved (or none exists)."""
    completed_at = _latest_batch_completed_at()
    if completed_at is None:
        return False
    model_at = model_updated_at()
    if model_at is not None and completed_at <= model_at:
        return False
    retrain()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch transaction classification pipeline.")
    parser.add_argument(
        "--complete",
        metavar="BATCH_ID",
        type=int,
        help="Complete a reviewed batch and insert into data_feed_history.",
    )
    args = parser.parse_args()

    if args.complete is not None:
        cmd_complete(args.complete)
    else:
        cmd_process()


if __name__ == "__main__":
    main()
