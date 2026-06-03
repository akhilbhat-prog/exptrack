"""
Flask entry point for the HDFC statement loader Cloud Run service.

Cloud Scheduler hits GET / daily at 9 PM IST, which triggers Gmail polling,
categorization, and a nightly summary email.

For local development:
    cd loader && PORT=5000 python app.py
"""

import os

from dotenv import load_dotenv
from datetime import date as _date
from flask import Flask, jsonify
from history import history_bp
from review import review_bp
from recurring import recurring_bp
from werkzeug.exceptions import HTTPException
from gmail_poller import (
    _build_gmail_service,
    main,
    run_categorization,
    run_parser_tests,
    send_summary_email,
)

load_dotenv()

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(_project_root, "templates"))
app.register_blueprint(review_bp)
app.register_blueprint(history_bp)
app.register_blueprint(recurring_bp)

import db as _db
import logging as _logging
try:
    _startup_conn = _db.get_connection()
    _db.create_tables(_startup_conn)
    _db.create_data_feed_table(_startup_conn)
    _db.create_recurring_table(_startup_conn)
    _startup_conn.close()
except Exception as _e:
    _logging.getLogger(__name__).warning("DB table setup skipped at startup: %s", _e)


@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return jsonify({"error": e.description, "code": e.code}), e.code


@app.route("/", methods=["GET", "POST"])
def trigger():
    service = _build_gmail_service()
    summary = main(service)
    cat_status = run_categorization()
    test_output = run_parser_tests()

    _recurring_count = 0
    if _date.today().day == 1:
        try:
            _rec_conn = _db.get_connection()
            _recurring_count = len(_db.generate_recurring_entries(_rec_conn))
            _rec_conn.close()
        except Exception as _re:
            _logging.getLogger(__name__).warning("Recurring generation failed: %s", _re)

    send_summary_email(service, summary, test_output, categorization_status=cat_status)

    no_transactions = summary["processed"] == 0 and summary["skipped"] == 0
    return jsonify({
        "status": "ok" if summary["failed"] == 0 else "partial_failure",
        "processed": summary["processed"],
        "skipped": summary["skipped"],
        "failed": summary["failed"],
        "recurring_generated": _recurring_count,
        "message": (
            "No new transactions found."
            if no_transactions
            else f"{summary['processed']} transaction(s) processed."
        ),
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
