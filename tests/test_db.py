"""
Unit tests for loader/db.py.

All functions take an explicit `conn` parameter so tests inject a mock
connection directly — no patching of psycopg2.connect needed.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import db


def _make_mock_conn(fetchone=None, fetchall=None, rowcount=1):
    """Return a (mock_conn, mock_cursor) pair with configurable cursor behaviour."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone
    mock_cursor.fetchall.return_value = fetchall or []
    mock_cursor.rowcount = rowcount
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# find_duplicate_transaction
# ---------------------------------------------------------------------------

class TestFindDuplicateTransaction:
    def test_upi_match_returns_message_id(self):
        mock_conn, mock_cursor = _make_mock_conn(fetchone=("msg_abc",))
        txn = {"upi_ref": "ref001", "amount": Decimal("100"), "date": datetime.now(timezone.utc), "format": "upi", "merchant": "AMAZON"}
        result = db.find_duplicate_transaction(mock_conn, txn)
        assert result == "msg_abc"
        assert "upi_ref" in mock_cursor.execute.call_args[0][0]

    def test_upi_no_match_returns_none(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        txn = {"upi_ref": "ref_missing", "amount": Decimal("50"), "date": datetime.now(timezone.utc), "format": "upi", "merchant": "SWIGGY"}
        assert db.find_duplicate_transaction(mock_conn, txn) is None

    def test_non_upi_match_uses_fallback_query(self):
        mock_conn, mock_cursor = _make_mock_conn(fetchone=("msg_xyz",))
        txn = {"upi_ref": None, "amount": Decimal("200"), "date": datetime(2026, 5, 1, tzinfo=timezone.utc), "format": "netbanking", "merchant": "HDFC Bank"}
        result = db.find_duplicate_transaction(mock_conn, txn)
        assert result == "msg_xyz"
        sql = mock_cursor.execute.call_args[0][0]
        assert "amount" in sql and "merchant" in sql

    def test_non_upi_no_match_returns_none(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        txn = {"upi_ref": None, "amount": Decimal("75"), "date": datetime(2026, 5, 1, tzinfo=timezone.utc), "format": "debit_card", "merchant": "ZARA"}
        assert db.find_duplicate_transaction(mock_conn, txn) is None

    def test_absent_upi_ref_key_uses_fallback_query(self):
        """Transaction dict without 'upi_ref' key falls through to the non-UPI path."""
        mock_conn, mock_cursor = _make_mock_conn(fetchone=("msg_no_key",))
        txn = {"amount": Decimal("300"), "date": datetime(2026, 5, 1, tzinfo=timezone.utc), "format": "debit_card", "merchant": "BIGBASKET"}
        result = db.find_duplicate_transaction(mock_conn, txn)
        assert result == "msg_no_key"
        assert "amount" in mock_cursor.execute.call_args[0][0]


# ---------------------------------------------------------------------------
# update_history_row
# ---------------------------------------------------------------------------

class TestUpdateHistoryRow:
    def test_normal_update_returns_computed_amounts(self):
        mock_conn, _ = _make_mock_conn(fetchone=(Decimal("100.00"),), rowcount=1)
        result = db.update_history_row(mock_conn, 1, {"divide_by": 2, "share_ratio": 0.5})
        assert result == {"monthly_amount": 50.0, "final_amount": 25.0}

    def test_divide_by_zero_clamped_to_one(self):
        """divide_by=0 is silently clamped to 1 via max(1, int(0 or 1))."""
        mock_conn, _ = _make_mock_conn(fetchone=(Decimal("200.00"),), rowcount=1)
        result = db.update_history_row(mock_conn, 1, {"divide_by": 0, "share_ratio": 1.0})
        assert result == {"monthly_amount": 200.0, "final_amount": 200.0}

    def test_share_ratio_none_defaults_to_one(self):
        mock_conn, _ = _make_mock_conn(fetchone=(Decimal("150.00"),), rowcount=1)
        result = db.update_history_row(mock_conn, 1, {"divide_by": 1, "share_ratio": None})
        assert result == {"monthly_amount": 150.0, "final_amount": 150.0}

    def test_row_not_found_returns_none(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        assert db.update_history_row(mock_conn, 999, {"divide_by": 1}) is None

    def test_commit_called_on_success(self):
        mock_conn, _ = _make_mock_conn(fetchone=(Decimal("50.00"),), rowcount=1)
        db.update_history_row(mock_conn, 1, {})
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# is_already_processed
# ---------------------------------------------------------------------------

class TestIsAlreadyProcessed:
    def test_found_returns_true(self):
        mock_conn, _ = _make_mock_conn(fetchone=(1,))
        assert db.is_already_processed(mock_conn, "msg123") is True

    def test_not_found_returns_false(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        assert db.is_already_processed(mock_conn, "msg_missing") is False


# ---------------------------------------------------------------------------
# insert_transaction
# ---------------------------------------------------------------------------

class TestInsertTransaction:
    def _txn(self, **overrides):
        base = {
            "date": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "amount": Decimal("500.00"),
            "type": "debit",
            "format": "upi",
            "account_last4": "1234",
            "card_last4": None,
            "vpa": "merchant@upi",
            "merchant": "ZOMATO",
            "raw_entry": "raw text",
            "upi_ref": "ref999",
        }
        return {**base, **overrides}

    def test_execute_and_commit_called(self):
        mock_conn, mock_cursor = _make_mock_conn()
        db.insert_transaction(mock_conn, self._txn(), "gmsg001")
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_all_optional_fields_none_no_crash(self):
        mock_conn, mock_cursor = _make_mock_conn()
        db.insert_transaction(
            mock_conn,
            self._txn(vpa=None, upi_ref=None, account_last4=None, card_last4=None),
            "gmsg002",
        )
        mock_cursor.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_history_page
# ---------------------------------------------------------------------------

class TestGetHistoryPage:
    def _row(self):
        return (
            1,                   # id
            date(2026, 5, 1),    # entry_date
            "May-2026",          # time_period
            "ZOMATO",            # merchant
            "Food delivery",     # entry_text
            Decimal("150.00"),   # amount
            "Food",              # category
            "Eating Out",        # sub_category
            "Expense",           # spend_type
            "O",                 # cadence
            1,                   # divide_by
            Decimal("150.00"),   # monthly_amount
            "N",                 # shared_expense
            Decimal("1.0"),      # share_ratio
            Decimal("150.00"),   # final_amount
        )

    def test_returns_pagination_structure(self):
        mock_conn, _ = _make_mock_conn(fetchone=(3,), fetchall=[self._row()])
        result = db.get_history_page(mock_conn, "May-2026", 1, 25)
        assert result["total"] == 3
        assert result["page"] == 1
        assert result["pages"] == 1
        assert len(result["items"]) == 1

    def test_decimal_amounts_converted_to_float(self):
        mock_conn, _ = _make_mock_conn(fetchone=(1,), fetchall=[self._row()])
        item = db.get_history_page(mock_conn, "May-2026", 1, 25)["items"][0]
        assert isinstance(item["amount"], float)
        assert isinstance(item["monthly_amount"], float)
        assert isinstance(item["final_amount"], float)
        assert item["amount"] == 150.0

    def test_empty_period_returns_empty_items(self):
        mock_conn, _ = _make_mock_conn(fetchone=(0,), fetchall=[])
        result = db.get_history_page(mock_conn, "Jan-2020", 1, 25)
        assert result["items"] == []
        assert result["total"] == 0
        assert result["pages"] == 1  # max(1, 0) → 1


# ---------------------------------------------------------------------------
# get_history_periods
# ---------------------------------------------------------------------------

class TestGetHistoryPeriods:
    def test_returns_period_list(self):
        mock_conn, _ = _make_mock_conn(fetchall=[("May-2026", 10), ("Apr-2026", 8)])
        result = db.get_history_periods(mock_conn)
        assert result == [{"period": "May-2026", "count": 10}, {"period": "Apr-2026", "count": 8}]

    def test_empty_table_returns_empty_list(self):
        mock_conn, _ = _make_mock_conn(fetchall=[])
        assert db.get_history_periods(mock_conn) == []


# ---------------------------------------------------------------------------
# delete_history_row
# ---------------------------------------------------------------------------

class TestDeleteHistoryRow:
    def test_deleted_returns_true(self):
        mock_conn, _ = _make_mock_conn(rowcount=1)
        assert db.delete_history_row(mock_conn, 42) is True

    def test_not_found_returns_false(self):
        mock_conn, _ = _make_mock_conn(rowcount=0)
        assert db.delete_history_row(mock_conn, 999) is False


# ---------------------------------------------------------------------------
# log_email
# ---------------------------------------------------------------------------

class TestLogEmail:
    def test_execute_and_commit_called(self):
        mock_conn, mock_cursor = _make_mock_conn()
        db.log_email(mock_conn, "msg_log01", "success")
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_notes_none_does_not_raise(self):
        mock_conn, _ = _make_mock_conn()
        db.log_email(mock_conn, "msg_log02", "failed", notes=None)


# ---------------------------------------------------------------------------
# insert_data_feed_row
# ---------------------------------------------------------------------------

class TestInsertDataFeedRow:
    def test_returns_row_id_on_success(self):
        mock_conn, _ = _make_mock_conn(fetchone=(42,))
        result = db.insert_data_feed_row(
            mock_conn,
            entry_date=date(2026, 5, 1),
            entry_text="Grocery",
            sub_category="Supermarket",
            category="Food",
            spend_type="Expense",
            amount=Decimal("300.00"),
        )
        assert result == 42

    def test_optional_fields_passed_through(self):
        mock_conn, mock_cursor = _make_mock_conn(fetchone=(1,))
        db.insert_data_feed_row(
            mock_conn,
            entry_date=date(2026, 5, 1),
            entry_text="Grocery",
            sub_category="Supermarket",
            category="Food",
            spend_type="Expense",
            amount=Decimal("300.00"),
            merchant="DMART",
            vpa="dmart@upi",
            upi_ref="ref555",
            time_period="May-2026",
            cadence="M",
            divide_by=2,
            monthly_amount=Decimal("150.00"),
            shared_expense="Y",
            share_ratio=Decimal("0.5"),
            final_amount=Decimal("75.00"),
        )
        mock_cursor.execute.assert_called_once()
        args = mock_cursor.execute.call_args[0][1]
        assert "DMART" in args
        assert "May-2026" in args
