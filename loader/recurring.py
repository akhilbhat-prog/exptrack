"""
Flask Blueprint for managing recurring transaction definitions.

Routes:
  GET   /recurring                  — recurring transactions HTML page
  GET   /api/recurring              — list all definitions
  POST  /api/recurring              — create a new definition
  PUT   /api/recurring/<id>         — full update of a definition
  DELETE /api/recurring/<id>        — delete a definition
  POST  /api/recurring/generate     — generate this month's entries that are due now (same as the nightly run)

Auth: if ADMIN_TOKEN env var is set, all routes require a matching
      ?token= query param or Authorization: Bearer <token> header.
"""

from datetime import date as _date

from flask import Blueprint, abort, jsonify, request

import db
from token_auth import require_admin as _require_token

recurring_bp = Blueprint("recurring", __name__)


@recurring_bp.route("/api/recurring")
@_require_token
def list_recurring():
    conn = db.get_connection()
    try:
        items = db.get_recurring_transactions(conn)
        return jsonify(items)
    finally:
        conn.close()


@recurring_bp.route("/api/recurring", methods=["POST"])
@_require_token
def create_recurring():
    data = request.get_json(force=True)
    entry_text = (data.get("entry_text") or "").strip()
    amount_raw = data.get("amount")
    if not entry_text:
        abort(400, "entry_text is required")
    if amount_raw is None:
        abort(400, "amount is required")
    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        abort(400, "amount must be a number")

    payload = {
        "entry_text":     entry_text,
        "merchant":       (data.get("merchant") or "").strip() or None,
        "amount":         amount,
        "category":       (data.get("category") or "").strip() or None,
        "sub_category":   (data.get("sub_category") or "").strip() or None,
        "spend_type":     (data.get("spend_type") or "").strip() or None,
        "cadence":        (data.get("cadence") or "O").strip(),
        "divide_by":      max(1, int(data.get("divide_by") or 1)),
        "shared_expense": (data.get("shared_expense") or "N").strip().upper()[:1],
        "share_ratio":    _share_ratio(data),
        "active":         bool(data.get("active", True)),
        "day_of_month":   _day_of_month(data) or 1,
        "paid_by":        _paid_by(data) or "Akhil",
        # A new item starts next month unless asked to start this month (avoids duplicating a
        # month already entered by hand, now that generation runs every night).
        "start_month":    _start_month(bool(data.get("start_this_month"))),
    }
    conn = db.get_connection()
    try:
        db.create_recurring_table(conn)
        new_id = db.upsert_recurring_transaction(conn, payload)
        return jsonify({"ok": True, "id": new_id}), 201
    finally:
        conn.close()


def _day_of_month(data: dict) -> int | None:
    """Debit day 1-31 (31 = last day of shorter months); None when not supplied."""
    raw = data.get("day_of_month")
    if raw is None or raw == "":
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        abort(400, "day_of_month must be a whole number from 1 to 31")
    if str(raw).strip() not in (str(v), f"{v}.0") or not 1 <= v <= 31:
        abort(400, "day_of_month must be a whole number from 1 to 31")
    return v


def _paid_by(data: dict) -> str | None:
    raw = data.get("paid_by")
    if raw is None or raw == "":
        return None
    v = str(raw).strip()
    if v not in ("Akhil", "Aditi"):
        abort(400, "paid_by must be 'Akhil' or 'Aditi'")
    return v


def _start_month(start_this_month: bool) -> _date:
    today = db.today_ist()
    this_month = _date(today.year, today.month, 1)
    return this_month if start_this_month else db.add_months(this_month, 1)


def _share_ratio(data: dict) -> float:
    try:
        return db.parse_share_ratio(data.get("share_ratio"))
    except ValueError as e:
        abort(400, str(e))


@recurring_bp.route("/api/recurring/<int:row_id>", methods=["PUT"])
@_require_token
def update_recurring(row_id):
    data = request.get_json(force=True)
    entry_text = (data.get("entry_text") or "").strip()
    amount_raw = data.get("amount")
    if not entry_text:
        abort(400, "entry_text is required")
    if amount_raw is None:
        abort(400, "amount is required")
    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        abort(400, "amount must be a number")

    payload = {
        "entry_text":     entry_text,
        "merchant":       (data.get("merchant") or "").strip() or None,
        "amount":         amount,
        "category":       (data.get("category") or "").strip() or None,
        "sub_category":   (data.get("sub_category") or "").strip() or None,
        "spend_type":     (data.get("spend_type") or "").strip() or None,
        "cadence":        (data.get("cadence") or "O").strip(),
        "divide_by":      max(1, int(data.get("divide_by") or 1)),
        "shared_expense": (data.get("shared_expense") or "N").strip().upper()[:1],
        "share_ratio":    _share_ratio(data),
        "active":         bool(data.get("active", True)),
        "day_of_month":   _day_of_month(data),   # None -> keep stored value
        "paid_by":        _paid_by(data),
    }
    conn = db.get_connection()
    try:
        updated_id = db.upsert_recurring_transaction(conn, payload, row_id=row_id)
        if updated_id is None:
            abort(404, "Definition not found")
        return jsonify({"ok": True})
    finally:
        conn.close()


@recurring_bp.route("/api/recurring/<int:row_id>", methods=["DELETE"])
@_require_token
def delete_recurring(row_id):
    conn = db.get_connection()
    try:
        deleted = db.delete_recurring_transaction(conn, row_id)
        if not deleted:
            abort(404, "Definition not found")
        return ("", 204)
    finally:
        conn.close()


@recurring_bp.route("/api/recurring/generate", methods=["POST"])
@_require_token
def generate_recurring():
    date_param = request.args.get("date", "").strip()
    today = None
    if date_param:
        try:
            today = _date.fromisoformat(date_param)
        except ValueError:
            abort(400, "date must be YYYY-MM-DD")

    conn = db.get_connection()
    try:
        db.create_recurring_table(conn)
        generated = db.generate_recurring_entries(conn, today=today)
        return jsonify({"ok": True, "generated": generated, "count": len(generated)})
    finally:
        conn.close()
