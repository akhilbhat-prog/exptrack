import os

from evaluation.metrics import evaluate
from ingestion.database import parse_database
from models.registry import register_model
from models.train import train_category_model
from processing.cleaner import clean_entry
from processing.memory import MerchantMemory
from processing.pipeline import process_dataframe
from processing.rules import load_rules


DEFAULT_RULES_PATH = "config/rules.json"
DEFAULT_OUTPUT_PATH = "data/processed/output.csv"
USE_ML_FALLBACK = True


def load_model(training_df, rules_path: str = DEFAULT_RULES_PATH):
    """Return (rules, memory, model) trained on training_df from data_feed_history."""
    rules = load_rules(rules_path)
    memory = MerchantMemory()
    model = None
    if USE_ML_FALLBACK:
        df = training_df.copy()
        df["entry_clean"] = df["entry_raw"].map(clean_entry)
        model = train_category_model(df)
        register_model(model)
    return rules, memory, model


def main():
    df = parse_database()
    rules, memory, model = load_model(df)

    processed_df = process_dataframe(df, rules=rules, memory=memory, model=model)

    preview_columns = [
        "date",
        "entry_raw",
        "amount",
        "merchant",
        "pred_category",
        "pred_subcategory",
        "pred_type",
        "prediction_source",
        "confidence",
    ]
    available_preview_columns = [
        column for column in preview_columns if column in processed_df.columns
    ]

    print(f"Shape: {processed_df.shape}")
    print(f"Columns: {list(processed_df.columns)}")
    print(processed_df[available_preview_columns].head())

    evaluate(processed_df)
    os.makedirs(os.path.dirname(DEFAULT_OUTPUT_PATH), exist_ok=True)
    processed_df.to_csv(DEFAULT_OUTPUT_PATH, index=False)
    print(f"Saved processed output to {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
