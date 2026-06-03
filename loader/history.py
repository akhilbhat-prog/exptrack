"""
Flask Blueprint for the data_feed_history viewer/editor.

Routes:
  GET   /view                     — history HTML page
  GET   /api/history/periods      — distinct time_period values with row counts
  GET   /api/history              — paginated rows (?period=<p>&page=<n>)
  POST  /api/history              — create a manual entry (exclude_from_training=True)
  PATCH /api/history/<id>         — update editable fields for one row
  DELETE /api/history/<id>        — delete a row

Auth: if REVIEW_TOKEN env var is set, all routes require a matching
      ?token= query param or Authorization: Bearer <token> header.
"""

import os
from datetime import date as _date
from functools import wraps

from flask import Blueprint, abort, jsonify, render_template, request

import db

history_bp = Blueprint("history", __name__)


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


@history_bp.route("/view")
@_require_token
def view_page():
    token = os.environ.get("REVIEW_TOKEN", "")
    return render_template("view.html", review_token=token)


@history_bp.route("/api/history/periods")
@_require_token
def list_periods():
    conn = db.get_connection()
    try:
        periods = db.get_history_periods(conn)
        return jsonify(periods)
    finally:
        conn.close()


@history_bp.route("/api/history")
@_require_token
def list_history():
    period = request.args.get("period", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = min(5000, max(1, int(request.args.get("page_size", 25))))
    except (ValueError, TypeError):
        page_size = 25
    if not period:
        return jsonify({"items": [], "total": 0, "page": 1, "pages": 1})
    conn = db.get_connection()
    try:
        result = db.get_history_page(conn, period, page, page_size=page_size)
        return jsonify(result)
    finally:
        conn.close()


@history_bp.route("/api/history/summary")
@_require_token
def history_summary():
    period = request.args.get("period", "").strip()
    if not period:
        return jsonify({"top_categories": []})
    prev_period = request.args.get("prev_period", "").strip() or None
    conn = db.get_connection()
    try:
        result = db.get_history_summary(conn, period, prev_period)
        return jsonify(result)
    finally:
        conn.close()


@history_bp.route("/api/history", methods=["POST"])
@_require_token
def create_history():
    data = request.get_json(force=True)
    entry_date_str = (data.get("entry_date") or "").strip()
    entry_text = (data.get("entry_text") or "").strip()
    amount_raw = data.get("amount")
    if not entry_date_str or not entry_text or amount_raw is None:
        abort(400, "entry_date, entry_text, and amount are required")
    try:
        entry_date = _date.fromisoformat(entry_date_str)
    except ValueError:
        abort(400, "entry_date must be YYYY-MM-DD")
    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        abort(400, "amount must be a number")

    merchant = (data.get("merchant") or "").strip() or None
    category = (data.get("category") or "").strip() or None
    sub_category = (data.get("sub_category") or "").strip() or None
    spend_type = (data.get("spend_type") or "").strip() or None
    cadence = (data.get("cadence") or "O").strip()
    divide_by = max(1, int(data.get("divide_by") or 1))
    shared_expense = (data.get("shared_expense") or "N").strip().upper()[:1]
    share_ratio = float(data.get("share_ratio") or 1.0)
    monthly_amount = round(amount / divide_by, 2)
    final_amount = round(monthly_amount * share_ratio, 2)
    time_period = entry_date.strftime("%b-%Y")

    conn = db.get_connection()
    try:
        db.create_data_feed_table(conn)
        if cadence == 'A' and divide_by > 1:
            ids = []
            for i in range(divide_by):
                if i == 0:
                    period_date = entry_date
                else:
                    m = entry_date.month - 1 + i
                    period_date = _date(entry_date.year + m // 12, m % 12 + 1, 1)
                tp = period_date.strftime("%b-%Y")
                row_id = db.insert_data_feed_row(
                    conn, period_date, entry_text, sub_category, category, spend_type,
                    amount, merchant, None, None,
                    time_period=tp,
                    cadence=cadence,
                    divide_by=divide_by,
                    monthly_amount=monthly_amount,
                    shared_expense=shared_expense,
                    share_ratio=share_ratio,
                    final_amount=final_amount,
                    exclude_from_training=True,
                )
                ids.append(row_id)
            return jsonify({"ok": True, "ids": ids, "count": len(ids)}), 201
        else:
            row_id = db.insert_data_feed_row(
                conn, entry_date, entry_text, sub_category, category, spend_type,
                amount, merchant, None, None,
                time_period=time_period,
                cadence=cadence,
                divide_by=divide_by,
                monthly_amount=monthly_amount,
                shared_expense=shared_expense,
                share_ratio=share_ratio,
                final_amount=final_amount,
                exclude_from_training=True,
            )
            return jsonify({"ok": True, "id": row_id, "count": 1}), 201
    finally:
        conn.close()


@history_bp.route("/api/history/<int:row_id>", methods=["DELETE"])
@_require_token
def delete_history(row_id):
    conn = db.get_connection()
    try:
        found = db.delete_history_row(conn, row_id)
        if not found:
            abort(404, "Row not found")
        return ("", 204)
    finally:
        conn.close()


@history_bp.route("/api/history/<int:row_id>", methods=["PATCH"])
@_require_token
def update_history(row_id):
    data = request.get_json(force=True)
    raw_amount = data.get("amount")
    fields = {
        "amount":         float(raw_amount) if raw_amount is not None else None,
        "time_period":    (data.get("time_period") or "").strip() or None,
        "category":       (data.get("category") or "").strip(),
        "sub_category":   (data.get("sub_category") or "").strip(),
        "spend_type":     (data.get("spend_type") or "").strip(),
        "cadence":        (data.get("cadence") or "O").strip(),
        "divide_by":      max(1, int(data.get("divide_by") or 1)),
        "shared_expense": (data.get("shared_expense") or "N").strip().upper()[:1],
        "share_ratio":    float(data.get("share_ratio") or 1.0),
    }
    conn = db.get_connection()
    try:
        result = db.update_history_row(conn, row_id, fields)
        if result is None:
            abort(404, "Row not found")
        return jsonify({"ok": True, **result})
    finally:
        conn.close()
