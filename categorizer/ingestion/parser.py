from __future__ import annotations

from pathlib import Path

import pandas as pd


COLUMN_ALIASES = {
    "id": "id",
    "date": "date",
    "transaction date": "date",
    "entry": "entry_raw",
    "entry text": "entry_raw",
    "entry_text": "entry_raw",
    "description": "entry_raw",
    "amount": "amount",
    "expense": "final_subcategory",
    "sub_category": "final_subcategory",
    "sub category": "final_subcategory",
    "category": "final_category",
    "type": "final_type",
    "spend_type": "final_type",
    "spend type": "final_type",
    "created_at": "created_at",
    "created at": "created_at",
    "merchant": "db_merchant",
    "db_merchant": "db_merchant",
    "db merchant": "db_merchant",
    "vpa": "vpa",
    "upi_ref": "upi_ref",
    "upi ref": "upi_ref",
}


def _normalize_columns(columns: list[str]) -> list[str]:
    normalized = []
    for column in columns:
        key = str(column).strip().lower()
        normalized.append(COLUMN_ALIASES.get(key, key))
    return normalized


def _parse_dates(date_series: pd.Series) -> pd.Series:
    """
    Parse workbook dates using the expected day-first format first, then fall
    back to a broader parser only for rows that do not match exactly.
    """
    text_dates = date_series.astype(str).str.strip()

    parsed = pd.to_datetime(text_dates, format="%d/%m/%y", errors="coerce")

    missing_mask = parsed.isna()
    if missing_mask.any():
        parsed.loc[missing_mask] = pd.to_datetime(
            text_dates.loc[missing_mask],
            errors="coerce",
            dayfirst=True,
        )

    return parsed


def parse_file(file_path: str) -> pd.DataFrame:
    """
    Detect file type, load it into a DataFrame, normalize expected column names,
    and return the parsed schema plus any available final label columns.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    df.columns = _normalize_columns(df.columns.tolist())

    required_columns = ["date", "entry_raw", "amount"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(
            f"Missing required columns after normalization: {missing_columns}"
        )

    optional_columns = [
        column
        for column in [
            "id",
            "final_category",
            "final_subcategory",
            "final_type",
            "created_at",
            "db_merchant",
            "vpa",
            "upi_ref",
        ]
        if column in df.columns
    ]
    selected_columns = required_columns + optional_columns

    parsed = df.loc[:, selected_columns].copy()
    parsed["date"] = _parse_dates(parsed["date"])
    parsed["entry_raw"] = parsed["entry_raw"].fillna("").astype(str)
    parsed["amount"] = pd.to_numeric(parsed["amount"], errors="coerce")

    if "id" in parsed.columns:
        parsed["id"] = pd.to_numeric(parsed["id"], errors="coerce").astype("Int64")

    if "created_at" in parsed.columns:
        parsed["created_at"] = pd.to_datetime(parsed["created_at"], errors="coerce")

    for column in optional_columns:
        if column in {"id", "created_at"}:
            continue
        parsed[column] = parsed[column].fillna("").astype(str).str.strip()

    return parsed
