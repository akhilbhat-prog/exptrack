"""
Flask Blueprint for the batch review UI.

Routes:
  GET  /review                              — review HTML page
  GET  /api/batches                         — list pending/reviewed batches
  GET  /api/batches/<id>                    — batch details + items
  PATCH /api/batches/<id>/items/<txn_id>    — save edits (category/subcategory/type)
  POST /api/batches/<id>/mark-reviewed      — set batch status = 'reviewed'
  POST /api/batches/<id>/complete           — complete batch, trigger retraining
  GET  /api/categories                      — category→subcategory map from rules.json

Auth: if REVIEW_TOKEN env var is set, all routes require a matching
      ?token= query param or Authorization: Bearer <token> header.
"""

import json
import logging
import os
import subprocess
import sys
from functools import wraps

from flask import Blueprint, abort, jsonify, render_template, request

import db

logger = logging.getLogger(__name__)

review_bp = Blueprint("review", __name__)

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RULES_PATH = os.path.join(_project_root, "categorizer", "config", "rules.json")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _require_token(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = os.environ.get("REVIEW_TOKEN", "")
        if not token:
            return f(*args, **kwargs)
        provided = request.args.get("token") or (
            request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )
        if provided != token:
            abort(401)
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

@review_bp.route("/review")
@_require_token
def review_page():
    token = os.environ.get("REVIEW_TOKEN", "")
    return render_template("review.html", review_token=token)


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@review_bp.route("/api/batches")
@_require_token
def list_batches():
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, row_count, status, created_at
                FROM transaction_batches
                WHERE status != 'complete'
                ORDER BY created_at DESC
            """)
            rows = cur.fetchall()
        return jsonify([
            {
                "id": r[0],
                "row_count": r[1],
                "status": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ])
    finally:
        conn.close()


@review_bp.route("/api/batches/<int:batch_id>")
@_require_token
def get_batch(batch_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, row_count, status, created_at FROM transaction_batches WHERE id = %s",
                (batch_id,),
            )
            b = cur.fetchone()
            if not b:
                abort(404, "Batch not found")
            batch = {
                "id": b[0],
                "row_count": b[1],
                "status": b[2],
                "created_at": b[3].isoformat() if b[3] else None,
            }

            cur.execute("""
                SELECT tbi.transaction_id,
                       tbi.pred_category, tbi.pred_subcategory, tbi.pred_type,
                       tbi.pred_confidence, tbi.pred_source,
                       tbi.category, tbi.subcategory, tbi.type,
                       t.date, t.raw_entry, t.amount, t.merchant, t.vpa
                FROM transaction_batch_items tbi
                JOIN transactions t ON t.id = tbi.transaction_id
                WHERE tbi.batch_id = %s
                ORDER BY t.date, t.id
            """, (batch_id,))
            rows = cur.fetchall()

        items = [
            {
                "transaction_id": r[0],
                "pred_category":    r[1],
                "pred_subcategory": r[2],
                "pred_type":        r[3],
                "pred_confidence":  float(r[4]) if r[4] is not None else None,
                "pred_source":      r[5],
                "category":         r[6],
                "subcategory":      r[7],
                "type":             r[8],
                "date":             r[9].isoformat() if r[9] else None,
                "raw_entry":        r[10],
                "amount":           float(r[11]) if r[11] is not None else None,
                "merchant":         r[12],
                "vpa":              r[13],
            }
            for r in rows
        ]
        return jsonify({"batch": batch, "items": items})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Item edits
# ---------------------------------------------------------------------------

@review_bp.route("/api/batches/<int:batch_id>/items/<int:txn_id>", methods=["PATCH"])
@_require_token
def update_item(batch_id, txn_id):
    data = request.get_json(force=True)
    category   = (data.get("category")   or "").strip()
    subcategory = (data.get("subcategory") or "").strip()
    txn_type   = (data.get("type")        or "").strip()

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE transaction_batch_items
                SET category = %s, subcategory = %s, type = %s
                WHERE batch_id = %s AND transaction_id = %s
                """,
                (category, subcategory, txn_type, batch_id, txn_id),
            )
            if cur.rowcount == 0:
                abort(404, "Item not found")
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Batch lifecycle
# ---------------------------------------------------------------------------

@review_bp.route("/api/batches/<int:batch_id>/mark-reviewed", methods=["POST"])
@_require_token
def mark_reviewed(batch_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM transaction_batches WHERE id = %s",
                (batch_id,),
            )
            row = cur.fetchone()
            if not row:
                abort(404, "Batch not found")
            if row[0] == "reviewed":
                return jsonify({"ok": True, "status": "reviewed"})
            if row[0] != "pending":
                abort(400, f"Batch is '{row[0]}', cannot mark as reviewed")
            cur.execute(
                "UPDATE transaction_batches SET status = 'reviewed' WHERE id = %s",
                (batch_id,),
            )
        conn.commit()
        return jsonify({"ok": True, "status": "reviewed"})
    finally:
        conn.close()


@review_bp.route("/api/batches/<int:batch_id>/complete", methods=["POST"])
@_require_token
def complete_batch(batch_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM transaction_batches WHERE id = %s",
                (batch_id,),
            )
            row = cur.fetchone()
            if not row:
                abort(404, "Batch not found")
            if row[0] != "reviewed":
                abort(400, f"Batch must be 'reviewed' before completing (current: '{row[0]}')")

        db.create_data_feed_table(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.date, t.raw_entry, t.amount,
                       COALESCE(NULLIF(TRIM(tbi.category),    ''), tbi.pred_category)    AS category,
                       COALESCE(NULLIF(TRIM(tbi.subcategory), ''), tbi.pred_subcategory) AS subcategory,
                       COALESCE(NULLIF(TRIM(tbi.type),        ''), tbi.pred_type)        AS txn_type
                FROM transaction_batch_items tbi
                JOIN transactions t ON t.id = tbi.transaction_id
                WHERE tbi.batch_id = %s
                """,
                (batch_id,),
            )
            items = cur.fetchall()

        inserted = 0
        for date, entry, amount, category, subcategory, txn_type in items:
            if db.insert_data_feed_row(conn, date, entry, subcategory, category, txn_type, amount):
                inserted += 1

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE transaction_batches SET status = 'complete', completed_at = NOW() WHERE id = %s",
                (batch_id,),
            )
        conn.commit()

        _trigger_retraining()
        return jsonify({"ok": True, "inserted": inserted})
    finally:
        conn.close()


def _trigger_retraining():
    main_py = os.path.join(_project_root, "categorizer", "main.py")
    if not os.path.exists(main_py):
        return
    try:
        subprocess.Popen(
            [sys.executable, main_py],
            cwd=os.path.join(_project_root, "categorizer"),
        )
        logger.info("Model retraining triggered in background.")
    except Exception:
        logger.exception("Failed to trigger model retraining.")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@review_bp.route("/api/categories")
@_require_token
def get_categories():
    """Return category → sorted subcategory list derived from rules.json."""
    try:
        with open(_RULES_PATH, encoding="utf-8") as f:
            rules = json.load(f)
    except Exception:
        return jsonify({})

    cat_map: dict[str, set] = {}
    for rule in rules.values():
        cat = rule.get("category", "")
        sub = rule.get("subcategory", "")
        if cat:
            cat_map.setdefault(cat, set()).add(sub)

    return jsonify({cat: sorted(subs) for cat, subs in sorted(cat_map.items())})
