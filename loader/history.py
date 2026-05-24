"""
Flask Blueprint for the data_feed_history viewer/editor.

Routes:
  GET  /view                     — history HTML page
  GET  /api/history/periods      — distinct time_period values with row counts
  GET  /api/history              — paginated rows (?period=<p>&page=<n>)
  PATCH /api/history/<id>        — update editable fields for one row

Auth: if REVIEW_TOKEN env var is set, all routes require a matching
      ?token= query param or Authorization: Bearer <token> header.
"""

import os
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
    if not period:
        return jsonify({"items": [], "total": 0, "page": 1, "pages": 1})
    conn = db.get_connection()
    try:
        result = db.get_history_page(conn, period, page)
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
    fields = {
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
