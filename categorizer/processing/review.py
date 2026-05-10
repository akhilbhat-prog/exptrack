from __future__ import annotations

import pandas as pd

from processing.cleaner import clean_entry
from processing.merchant import extract_merchant
from processing.rules import apply_rules


def review_rules(rules: dict) -> pd.DataFrame:
    """
    Convert the rule dictionary into a review-friendly table.
    """
    rows = []

    for keyword, mapping in rules.items():
        rows.append(
            {
                "keyword": keyword,
                "category": mapping.get("category", "Unknown"),
                "subcategory": mapping.get("subcategory", "Unknown"),
                "type": mapping.get("type", "Unknown"),
                "confidence": float(mapping.get("confidence", 0.0)),
            }
        )

    return pd.DataFrame(rows).sort_values("keyword").reset_index(drop=True)


def find_unidentified_entries(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """
    Return transactions that are not identifiable by the current rules.

    A row is considered unidentified when:
    - no merchant can be extracted, or
    - the cleaned text does not match any configured rule
    """
    review_df = df.copy()
    review_df["entry_clean"] = review_df["entry_raw"].map(clean_entry)
    review_df["merchant"] = review_df["entry_clean"].map(extract_merchant)
    review_df["rule_match"] = review_df.apply(
        lambda row: apply_rules(row["entry_clean"], rules, amount=row["amount"]),
        axis=1,
    )

    review_df["review_reason"] = review_df.apply(_get_review_reason, axis=1)

    unidentified = review_df.loc[
        review_df["review_reason"].notna(),
        _available_columns(
            review_df,
            [
                "id",
                "date",
                "created_at",
                "entry_raw",
                "entry_clean",
                "merchant",
                "db_merchant",
                "vpa",
                "upi_ref",
                "amount",
                "review_reason",
            ],
        ),
    ].copy()

    return unidentified.reset_index(drop=True)


def summarize_unidentified_entries(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """
    Group unidentified transactions so repeated unknowns are easier to review.
    """
    unidentified = find_unidentified_entries(df, rules)
    if unidentified.empty:
        return unidentified

    summary = (
        unidentified.groupby(
            ["merchant", "entry_clean", "review_reason"], dropna=False
        )
        .agg(
            occurrences=("entry_raw", "size"),
            sample_entry=("entry_raw", "first"),
            total_amount=("amount", "sum"),
        )
        .reset_index()
        .sort_values(["occurrences", "merchant"], ascending=[False, True])
        .reset_index(drop=True)
    )

    return summary


def find_rule_failures(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """
    Return transactions whose cleaned text does not match any configured rule.
    """
    review_df = df.copy()
    review_df["entry_clean"] = review_df["entry_raw"].map(clean_entry)
    review_df["merchant"] = review_df["entry_clean"].map(extract_merchant)
    review_df["rule_match"] = review_df.apply(
        lambda row: apply_rules(row["entry_clean"], rules, amount=row["amount"]),
        axis=1,
    )

    failed = review_df.loc[review_df["rule_match"].isna()].copy()
    failed["review_reason"] = "no_rule_match"

    return failed.loc[
        :,
        _available_columns(
            failed,
            [
                "id",
                "date",
                "created_at",
                "entry_raw",
                "entry_clean",
                "merchant",
                "db_merchant",
                "vpa",
                "upi_ref",
                "amount",
                "final_category",
                "final_subcategory",
                "final_type",
                "review_reason",
            ],
        ),
    ].reset_index(drop=True)


def summarize_rule_failures(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """
    Group rule failures so repeated DB values are easier to correct.
    """
    failed = find_rule_failures(df, rules)
    if failed.empty:
        return failed

    group_columns = ["entry_clean", "merchant"]
    if "db_merchant" in failed.columns:
        group_columns.append("db_merchant")
    for column in ["final_category", "final_subcategory", "final_type"]:
        if column in failed.columns:
            group_columns.append(column)

    aggregations = {
        "occurrences": ("entry_raw", "size"),
        "sample_entry": ("entry_raw", "first"),
        "total_amount": ("amount", "sum"),
    }
    if "date" in failed.columns:
        aggregations["first_date"] = ("date", "min")
        aggregations["last_date"] = ("date", "max")

    summary = (
        failed.groupby(group_columns, dropna=False)
        .agg(**aggregations)
        .reset_index()
        .sort_values(["occurrences", "entry_clean"], ascending=[False, True])
        .reset_index(drop=True)
    )

    return summary


def _available_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in df.columns]


def _get_review_reason(row: pd.Series) -> str | None:
    if row["merchant"] == "unknown":
        return "merchant_unknown"

    if row["rule_match"] is None:
        return "no_rule_match"

    return None
