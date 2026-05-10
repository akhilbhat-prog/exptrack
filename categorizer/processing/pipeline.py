from __future__ import annotations

import pandas as pd

from models.predict import predict_category
from processing.cleaner import clean_entry, extract_vpa_handle
from processing.merchant import extract_merchant
from processing.rules import apply_rules


def build_combined_text(entry_clean: str, vpa: str) -> str:
    parts = [entry_clean or ""]
    vpa_handle = extract_vpa_handle(vpa) if vpa else ""
    if vpa_handle:
        parts.append(vpa_handle)
    return " ".join(parts).strip()


def predict_row(row, rules: dict, memory, model=None) -> dict:
    """
    Predict category metadata for a single transaction row.
    """
    merchant = row.get("merchant", "")
    text_combined = row.get("text_combined") or row.get("entry_clean", "")
    amount = row.get("amount")

    memory_match = memory.lookup(merchant)
    if memory_match is not None:
        return {
            "category": memory_match.get("category", "Unknown"),
            "subcategory": memory_match.get("subcategory", "Unknown"),
            "type": memory_match.get("type", "Unknown"),
            "confidence": float(memory_match.get("confidence", 0.0)),
            "source": "memory",
        }

    rule_match = apply_rules(text_combined, rules, amount=amount)
    if rule_match is not None:
        return {
            "category": rule_match.get("category", "Unknown"),
            "subcategory": rule_match.get("subcategory", "Unknown"),
            "type": rule_match.get("type", "Unknown"),
            "confidence": float(rule_match.get("confidence", 0.0)),
            "source": "rule",
        }

    if model is not None:
        ml_match = predict_category(model, text_combined, amount=amount)
        return {
            "category": ml_match.get("category", "Unknown"),
            "subcategory": ml_match.get("subcategory", "Unknown"),
            "type": ml_match.get("type", "Unknown"),
            "confidence": float(ml_match.get("confidence", 0.0)),
            "source": "ml",
        }

    return {
        "category": "Unknown",
        "subcategory": "Unknown",
        "type": "Unknown",
        "confidence": 0.0,
        "source": "none",
    }


def process_dataframe(df: pd.DataFrame, rules: dict, memory, model=None) -> pd.DataFrame:
    """
    Clean transactions, extract merchants, and populate prediction columns.
    """
    processed = df.copy()
    processed["entry_clean"] = processed["entry_raw"].map(clean_entry)
    processed["merchant"] = processed["entry_clean"].map(extract_merchant)
    processed["text_combined"] = processed.apply(
        lambda row: build_combined_text(
            row.get("entry_clean", ""),
            row.get("vpa", ""),
        ),
        axis=1,
    )

    predictions = processed.apply(
        lambda row: predict_row(row, rules=rules, memory=memory, model=model),
        axis=1,
    )
    predictions_df = pd.DataFrame(predictions.tolist(), index=processed.index)

    processed["pred_category"] = predictions_df["category"]
    processed["pred_subcategory"] = predictions_df["subcategory"]
    processed["pred_type"] = predictions_df["type"]
    processed["prediction_source"] = predictions_df["source"]
    processed["confidence"] = predictions_df["confidence"]

    return processed
