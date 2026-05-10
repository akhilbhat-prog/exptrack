from __future__ import annotations

import pandas as pd


TARGET_COLUMN_PAIRS = [
    ("pred_category", "final_category"),
    ("pred_subcategory", "final_subcategory"),
    ("pred_type", "final_type"),
]


def evaluate(df: pd.DataFrame) -> dict:
    """
    Compute exact-match accuracy overall and by prediction source.
    """
    required_columns = [
        "prediction_source",
        *[pred for pred, _ in TARGET_COLUMN_PAIRS],
        *[final for _, final in TARGET_COLUMN_PAIRS],
    ]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required evaluation columns: {missing_columns}")

    evaluated_df = df.copy()
    evaluated_df["is_labeled"] = evaluated_df.apply(_is_labeled_row, axis=1)
    evaluated_df["is_correct"] = evaluated_df.apply(_is_correct_row, axis=1)

    labeled_rows = evaluated_df.loc[evaluated_df["is_labeled"]].copy()
    if labeled_rows.empty:
        print("No labeled rows available for evaluation.")
        return {
            "overall_accuracy": None,
            "labeled_rows": 0,
            "accuracy_by_source": {},
        }

    overall_accuracy = labeled_rows["is_correct"].mean()
    accuracy_by_source = (
        labeled_rows.groupby("prediction_source", dropna=False)["is_correct"]
        .mean()
        .to_dict()
    )

    print(f"Total labeled rows: {len(labeled_rows)}")
    print(f"Overall accuracy: {_format_accuracy(overall_accuracy)}")

    for source in ["memory", "rule", "ml", "none"]:
        if source in accuracy_by_source:
            print(f"{source} accuracy: {_format_accuracy(accuracy_by_source[source])}")

    return {
        "overall_accuracy": overall_accuracy,
        "labeled_rows": int(len(labeled_rows)),
        "accuracy_by_source": accuracy_by_source,
    }


def _is_labeled_row(row: pd.Series) -> bool:
    for _, final_column in TARGET_COLUMN_PAIRS:
        value = row.get(final_column, "")
        if pd.isna(value) or str(value).strip() == "":
            return False

    return True


def _is_correct_row(row: pd.Series) -> bool:
    if not row["is_labeled"]:
        return False

    for pred_column, final_column in TARGET_COLUMN_PAIRS:
        pred_value = _normalize_value(row.get(pred_column, ""))
        final_value = _normalize_value(row.get(final_column, ""))
        if pred_value != final_value:
            return False

    return True


def _normalize_value(value) -> str:
    if pd.isna(value):
        return ""

    return str(value).strip().casefold()


def _format_accuracy(value: float) -> str:
    return f"{value:.2%}"
