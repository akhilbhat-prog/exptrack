from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ingestion.database import connect, parse_database
from ingestion.transactions import complete_batch, create_batch, fetch_transactions, insert_batch_items
from models.registry import load_model, register_model
from models.train import train_category_model
from processing.cleaner import clean_entry
from processing.memory import MerchantMemory
from processing.pipeline import process_dataframe
from processing.rules import load_rules

DEFAULT_RULES_PATH = Path(__file__).parent / "config" / "rules.json"


def cmd_process() -> None:
    print("Loading registered model...")
    model = load_model()

    rules = load_rules(DEFAULT_RULES_PATH)
    memory = MerchantMemory()

    print("Fetching transactions...")
    transactions_df = fetch_transactions()
    if transactions_df.empty:
        print("No new transactions to process.")
        return

    print(f"Running predictions on {len(transactions_df)} transactions...")
    processed_df = process_dataframe(transactions_df, rules=rules, memory=memory, model=model)

    with connect() as conn:
        batch_id = create_batch(conn, row_count=len(processed_df))
        insert_batch_items(conn, batch_id, processed_df)

    print(
        f"\nBatch #{batch_id} created — {len(processed_df)} rows.\n"
        f"Review and correct categories in: public.transaction_batch_items (batch_id = {batch_id})\n"
        f"When done, set status = 'reviewed' in: public.transaction_batches (id = {batch_id})\n"
        f"Then run: python batch_process.py --complete {batch_id}"
    )


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
    history_df = parse_database()
    history_df["entry_clean"] = history_df["entry_raw"].map(clean_entry)
    model = train_category_model(history_df)
    register_model(model)
    print("New model version registered as champion.")


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
