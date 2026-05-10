from __future__ import annotations

import os
from urllib.parse import quote_plus

import pandas as pd
import psycopg
from dotenv import load_dotenv


DEFAULT_TABLE_NAME = "public.data_feed_history"

QUERY = f"""
SELECT
    id AS id,
    entry_date AS date,
    entry_text AS entry_raw,
    amount AS amount,
    category AS final_category,
    sub_category AS final_subcategory,
    spend_type AS final_type,
    created_at AS created_at,
    merchant AS db_merchant,
    vpa AS vpa,
    upi_ref AS upi_ref
FROM {DEFAULT_TABLE_NAME}
ORDER BY entry_date, entry_text
"""

OUTPUT_COLUMNS = [
    "id",
    "date",
    "entry_raw",
    "amount",
    "final_category",
    "final_subcategory",
    "final_type",
    "created_at",
    "db_merchant",
    "vpa",
    "upi_ref",
]


def connect() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(build_database_url())


def parse_database() -> pd.DataFrame:
    """
    Load labeled transaction data from Neon Postgres and normalize it to the
    schema expected by the classification pipeline.
    """
    load_dotenv()
    database_url = build_database_url()

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(QUERY)
            rows = cursor.fetchall()
            columns = [description.name for description in cursor.description]

    df = pd.DataFrame(rows, columns=columns)

    return _normalize_database_frame(df)


def build_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "5432")
    database = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    missing_variables = [
        name
        for name, value in {
            "DB_HOST": host,
            "DB_NAME": database,
            "DB_USER": user,
            "DB_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing_variables:
        raise ValueError(
            "Database configuration is incomplete. Set DATABASE_URL or provide "
            f"these variables in .env: {missing_variables}"
        )

    encoded_user = quote_plus(user)
    encoded_password = quote_plus(password)

    return (
        f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{database}"
        "?sslmode=require&channel_binding=require"
    )


def _normalize_database_frame(df: pd.DataFrame) -> pd.DataFrame:
    missing_columns = [column for column in OUTPUT_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required database columns: {missing_columns}")

    parsed = df.loc[:, OUTPUT_COLUMNS].copy()
    parsed["id"] = pd.to_numeric(parsed["id"], errors="coerce").astype("Int64")
    parsed["date"] = pd.to_datetime(parsed["date"], errors="coerce")
    parsed["entry_raw"] = parsed["entry_raw"].fillna("").astype(str)
    parsed["amount"] = pd.to_numeric(parsed["amount"], errors="coerce")
    parsed["created_at"] = pd.to_datetime(parsed["created_at"], errors="coerce")

    for column in ["final_category", "final_subcategory", "final_type"]:
        parsed[column] = parsed[column].fillna("").astype(str).str.strip()

    for column in ["db_merchant", "vpa", "upi_ref"]:
        parsed[column] = parsed[column].fillna("").astype(str).str.strip()

    return parsed


def insert_data_feed_history(conn: psycopg.Connection, rows: list[dict]) -> None:
    """
    Bulk-insert completed batch rows into data_feed_history.

    Each dict in rows must have: entry_date, entry_text, amount, category,
    sub_category, spend_type, merchant, vpa, upi_ref.
    """
    sql = """
        INSERT INTO public.data_feed_history
            (entry_date, entry_text, amount, category, sub_category, spend_type,
             merchant, vpa, upi_ref)
        VALUES
            (%(entry_date)s, %(entry_text)s, %(amount)s, %(category)s,
             %(sub_category)s, %(spend_type)s, %(merchant)s, %(vpa)s, %(upi_ref)s)
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
