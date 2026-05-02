"""Generate SQL INSERT statements from Data Feed for Model.xlsx → data_feed_history.sql"""

import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

EXCEL_PATH = "Data Feed for Model.xlsx"
OUTPUT_PATH = "data_feed_history.sql"


def escape(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def main() -> None:
    import openpyxl

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb["Sheet1"]

    lines = [
        "CREATE TABLE IF NOT EXISTS data_feed_history (",
        "    id         SERIAL PRIMARY KEY,",
        "    date       DATE NOT NULL,",
        "    entry      TEXT NOT NULL,",
        "    expense    TEXT,",
        "    category   TEXT,",
        "    type       VARCHAR(20),",
        "    amount     NUMERIC(12, 2) NOT NULL,",
        "    created_at TIMESTAMPTZ DEFAULT NOW(),",
        "    UNIQUE (date, entry, amount)",
        ");",
        "",
    ]

    written = skipped = warnings = 0

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        date_s, entry, expense, category, type_, amount, *_ = row

        if not date_s or amount is None:
            logger.warning("Row %d: missing date or amount — skipping.", i)
            skipped += 1
            continue

        try:
            date = datetime.strptime(date_s, "%d/%m/%y").date()
        except ValueError:
            logger.warning("Row %d: unparseable date %r — skipping.", i, date_s)
            skipped += 1
            continue

        if category == date_s:
            logger.warning("Row %d: category looks like a date (%r) — including anyway.", i, category)
            warnings += 1

        lines.append(
            f"INSERT INTO data_feed_history (date, entry, expense, category, type, amount) "
            f"VALUES ({escape(date)}, {escape(entry)}, {escape(expense)}, "
            f"{escape(category)}, {escape(type_)}, {amount}) "
            f"ON CONFLICT (date, entry, amount) DO NOTHING;"
        )
        written += 1

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Done: {written} INSERT statements written to {OUTPUT_PATH} "
          f"({skipped} skipped, {warnings} warnings)")


if __name__ == "__main__":
    main()
