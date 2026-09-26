"""One-shot: propose (and, on request, apply) series_id for existing cadence 'A' rows.

Existing amortised rows predate series_id. This groups rows that look like one series:
same entry_text / merchant / category / sub_category / divide_by / amount, cadence 'A',
on consecutive calendar months. Default is a READ-ONLY dry run that numbers each proposed
group. Review it, then apply only the groups you approve:

    python loader/backfill_series_id.py                  # dry run, prints groups
    python loader/backfill_series_id.py --apply 1,4,7    # stamp those group numbers only

Group numbers are stable only for the same data, so re-run the dry run right before applying.
Requires the series_id column (created at app startup by db.create_data_feed_table).
"""

import argparse
from collections import defaultdict

import db


def find_groups(conn) -> list[list[dict]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, entry_date, entry_text, merchant, category, sub_category,
                   divide_by, amount
            FROM data_feed_history
            WHERE cadence = 'A' AND COALESCE(divide_by, 1) > 1 AND series_id IS NULL
            ORDER BY entry_text, merchant, category, sub_category, divide_by, amount, entry_date, id
            """
        )
        rows = cur.fetchall()

    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r[2], r[3], r[4], r[5], r[6], r[7])
        buckets[key].append({"id": r[0], "entry_date": r[1], "divide_by": r[6], "key": key})

    groups: list[list[dict]] = []
    for items in buckets.values():
        run: list[dict] = []
        for it in items:
            if run:
                prev = run[-1]["entry_date"]
                gap = (it["entry_date"].year - prev.year) * 12 + it["entry_date"].month - prev.month
                if gap != 1 or len(run) >= it["divide_by"]:
                    groups.append(run)
                    run = []
            run.append(it)
        if run:
            groups.append(run)
    return groups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", help="comma-separated group numbers to stamp with a new series_id")
    args = parser.parse_args()

    conn = db.get_connection()
    try:
        groups = find_groups(conn)
        chosen = {int(x) for x in args.apply.split(",")} if args.apply else set()
        for n, g in enumerate(groups, start=1):
            text, merchant, category, sub, divide_by, amount = g[0]["key"]
            status = "complete" if len(g) == divide_by else f"INCOMPLETE ({len(g)} of {divide_by})"
            print(f"[{n}] {text} | {merchant} | {category}/{sub} | amount={amount} | "
                  f"{g[0]['entry_date']} .. {g[-1]['entry_date']} | {status} | ids={[x['id'] for x in g]}")
            if n in chosen:
                sid = db.new_series_id()
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE data_feed_history SET series_id = %s WHERE id = ANY(%s)",
                        (sid, [x["id"] for x in g]),
                    )
                conn.commit()
                print(f"    -> stamped series_id {sid}")
        if not groups:
            print("No unlinked cadence-A rows found.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
