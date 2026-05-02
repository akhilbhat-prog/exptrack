"""One-shot loader: reads Data Feed for Model.xlsx → data_feed_history table."""

import logging
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()
import db

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

EXCEL_PATH = "Data Feed for Model.xlsx"


def main() -> None:
    import openpyxl

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb["Sheet1"]

    conn = db.get_connection()
    db.create_data_feed_table(conn)

    inserted = skipped = warnings = 0

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        date_s, entry, expense, category, type_, amount, *_ = row

        if not date_s or amount is None:
            logger.warning("Row %d: missing date or amount — skipping. %s", i, row)
            warnings += 1
            continue

        try:
            date = datetime.strptime(date_s, "%d/%m/%y").date()
        except ValueError:
            logger.warning("Row %d: unparseable date %r — skipping.", i, date_s)
            warnings += 1
            continue

        if category == date_s:
            logger.warning("Row %d: category looks like a date (%r) — loading anyway.", i, category)
            warnings += 1

        ok = db.insert_data_feed_row(conn, date, entry, expense, category, type_, amount)
        if ok:
            inserted += 1
        else:
            skipped += 1

    conn.close()
    print(f"Done: {inserted} inserted, {skipped} skipped (duplicates), {warnings} warnings")


if __name__ == "__main__":
    main()
