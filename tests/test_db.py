"""
Unit tests for loader/db.py.

All functions take an explicit `conn` parameter so tests inject a mock
connection directly — no patching of psycopg2.connect needed.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

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
    _FULL_ROW = (Decimal("100.00"), "May-2026", "Food", "Eating Out", "Expense", "O", 1, "N", Decimal("1.0"))

    def test_normal_update_returns_computed_amounts(self):
        mock_conn, _ = _make_mock_conn(fetchone=self._FULL_ROW, rowcount=1)
        result = db.update_history_row(mock_conn, 1, {"divide_by": 2, "share_ratio": 0.5})
        assert result["amount"] == 100.0
        assert result["monthly_amount"] == 50.0
        assert result["final_amount"] == 25.0
        assert result["divide_by"] == 2
        assert result["share_ratio"] == 0.5

    def test_divide_by_zero_clamped_to_one(self):
        """divide_by=0 is silently clamped to 1 via max(1, int(0 or 1))."""
        row = (Decimal("200.00"), "May-2026", "Food", "Eating Out", "Expense", "O", 1, "N", Decimal("1.0"))
        mock_conn, _ = _make_mock_conn(fetchone=row, rowcount=1)
        result = db.update_history_row(mock_conn, 1, {"divide_by": 0, "share_ratio": 1.0})
        assert result["amount"] == 200.0
        assert result["monthly_amount"] == 200.0
        assert result["final_amount"] == 200.0

    def test_share_ratio_none_defaults_to_one(self):
        row = (Decimal("150.00"), "May-2026", "Food", "Eating Out", "Expense", "O", 1, "N", Decimal("1.0"))
        mock_conn, _ = _make_mock_conn(fetchone=row, rowcount=1)
        result = db.update_history_row(mock_conn, 1, {"divide_by": 1, "share_ratio": None})
        assert result["amount"] == 150.0
        assert result["monthly_amount"] == 150.0
        assert result["final_amount"] == 150.0

    def test_row_not_found_returns_none(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        assert db.update_history_row(mock_conn, 999, {"divide_by": 1}) is None

    def test_commit_called_on_success(self):
        row = (Decimal("50.00"), "May-2026", "Food", "Eating Out", "Expense", "O", 1, "N", Decimal("1.0"))
        mock_conn, _ = _make_mock_conn(fetchone=row, rowcount=1)
        db.update_history_row(mock_conn, 1, {})
        mock_conn.commit.assert_called_once()

    def test_partial_update_preserves_untouched_fields(self):
        """Regression test: PATCHing only spend_type must not blank out category/sub_category."""
        row = (Decimal("100.00"), "May-2026", "Food", "Eating Out", "Expense", "O", 1, "N", Decimal("1.0"))
        mock_conn, mock_cursor = _make_mock_conn(fetchone=row, rowcount=1)
        result = db.update_history_row(mock_conn, 1, {"spend_type": "Investment"})
        assert result["category"] == "Food"
        assert result["sub_category"] == "Eating Out"
        assert result["spend_type"] == "Investment"
        update_sql, update_params = mock_cursor.execute.call_args_list[-1][0]
        assert "Food" in update_params
        assert "Eating Out" in update_params
        assert "Investment" in update_params


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
# get_transaction_by_message_id
# ---------------------------------------------------------------------------

class TestGetTransactionByMessageId:
    def test_found_returns_dict(self):
        ts = datetime(2026, 6, 27, 10, 0, 0, tzinfo=timezone.utc)
        mock_conn, _ = _make_mock_conn(fetchone=("Swiggy", Decimal("350.00"), "debit", ts))
        result = db.get_transaction_by_message_id(mock_conn, "msg123")
        assert result == {"merchant": "Swiggy", "amount": Decimal("350.00"), "type": "debit", "date": ts}

    def test_not_found_returns_none(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        assert db.get_transaction_by_message_id(mock_conn, "missing") is None


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


# ---------------------------------------------------------------------------
# get_history_row
# ---------------------------------------------------------------------------

class TestGetHistoryRow:
    def test_returns_dict_when_found(self):
        mock_conn, _ = _make_mock_conn(fetchone=(5, "Grocery run", date(2026, 5, 1), "May-2026", "BigBasket"))
        result = db.get_history_row(mock_conn, 5)
        assert result == {
            "id": 5, "entry_text": "Grocery run", "entry_date": date(2026, 5, 1),
            "time_period": "May-2026", "merchant": "BigBasket",
        }

    def test_returns_none_when_not_found(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        assert db.get_history_row(mock_conn, 999) is None


# ---------------------------------------------------------------------------
# get_settings / update_setting
# ---------------------------------------------------------------------------

class TestCreateSettingsTable:
    def test_seeds_three_default_rows(self):
        mock_conn, cur = _make_mock_conn()
        db.create_settings_table(mock_conn)
        sql = cur.execute.call_args[0][0]
        assert "'default_share_ratio', '0.7'" in sql
        assert "'default_annual_divisor', '12'" in sql
        assert "'shared_backfill_floor', '2026-09-20'" in sql
        mock_conn.commit.assert_called_once()


class TestGetSettings:
    def test_returns_typed_dict(self):
        mock_conn, _ = _make_mock_conn(fetchall=[("default_share_ratio", "0.7"), ("default_annual_divisor", "12")])
        result = db.get_settings(mock_conn)
        assert result["default_share_ratio"] == 0.7
        assert isinstance(result["default_share_ratio"], float)
        assert result["default_annual_divisor"] == 12
        assert isinstance(result["default_annual_divisor"], int)

    def test_shared_backfill_floor_returned_as_string(self):
        mock_conn, _ = _make_mock_conn(fetchall=[("shared_backfill_floor", "2026-09-20")])
        result = db.get_settings(mock_conn)
        assert result["shared_backfill_floor"] == "2026-09-20"
        assert isinstance(result["shared_backfill_floor"], str)

    def test_unknown_key_returned_as_string(self):
        mock_conn, _ = _make_mock_conn(fetchall=[("some_flag", "yes")])
        result = db.get_settings(mock_conn)
        assert result["some_flag"] == "yes"

    def test_empty_settings_returns_empty_dict(self):
        mock_conn, _ = _make_mock_conn(fetchall=[])
        assert db.get_settings(mock_conn) == {}


class TestUpdateSetting:
    def test_calls_execute_and_commit(self):
        mock_conn, mock_cursor = _make_mock_conn()
        db.update_setting(mock_conn, "default_share_ratio", "0.6")
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_sql_uses_on_conflict_upsert(self):
        mock_conn, mock_cursor = _make_mock_conn()
        db.update_setting(mock_conn, "default_share_ratio", "0.5")
        sql = mock_cursor.execute.call_args[0][0]
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql


# ---------------------------------------------------------------------------
# get_history_summary
# ---------------------------------------------------------------------------

class TestGetHistorySummary:
    def _row(self, category, total, count, period_total):
        return (category, Decimal(str(total)), count, Decimal(str(period_total)))

    def test_returns_top_categories_and_period_total(self):
        rows = [self._row("Food", 5000, 10, 8000), self._row("Transport", 3000, 5, 8000)]
        mock_conn, _ = _make_mock_conn(fetchall=rows)
        result = db.get_history_summary(mock_conn, "May-2026")
        assert result["period_total"] == 8000.0
        assert len(result["top_categories"]) == 2
        assert result["top_categories"][0]["category"] == "Food"
        assert result["top_categories"][0]["total"] == 5000.0
        assert result["top_categories"][0]["count"] == 10

    def test_returns_empty_when_no_rows(self):
        mock_conn, _ = _make_mock_conn(fetchall=[])
        result = db.get_history_summary(mock_conn, "Jan-2020")
        assert result["period_total"] == 0.0
        assert result["top_categories"] == []

    def test_with_prev_period_includes_prev_total(self):
        # row shape with prev_period: (cat, cur_total, prev_total, count, period_total)
        rows = [("Food", Decimal("5000"), Decimal("4000"), 10, Decimal("5000"))]
        mock_conn, _ = _make_mock_conn(fetchall=rows)
        result = db.get_history_summary(mock_conn, "May-2026", prev_period="Apr-2026")
        cat = result["top_categories"][0]
        assert cat["category"] == "Food"
        assert cat["total"] == 5000.0
        assert cat["prev_total"] == 4000.0
        assert cat["count"] == 10

    def test_with_prev_period_none_prev_total_is_none(self):
        rows = [("Food", Decimal("5000"), None, 10, Decimal("5000"))]
        mock_conn, _ = _make_mock_conn(fetchall=rows)
        result = db.get_history_summary(mock_conn, "May-2026", prev_period="Apr-2026")
        assert result["top_categories"][0]["prev_total"] is None


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------

class TestCreateUser:
    def test_returns_new_id(self):
        mock_conn, mock_cursor = _make_mock_conn(fetchone=(7,))
        result = db.create_user(mock_conn, "aditi", "hashed-pw")
        assert result == 7

    def test_executes_insert_with_username_and_hash(self):
        mock_conn, mock_cursor = _make_mock_conn(fetchone=(1,))
        db.create_user(mock_conn, "aditi", "hashed-pw")
        sql, params = mock_cursor.execute.call_args[0]
        assert "INSERT INTO users" in sql
        assert params[0] == "aditi"
        assert params[1] == "hashed-pw"

    def test_default_role_is_user(self):
        mock_conn, mock_cursor = _make_mock_conn(fetchone=(1,))
        db.create_user(mock_conn, "aditi", "hashed-pw")
        _, params = mock_cursor.execute.call_args[0]
        assert params[2] == "user"

    def test_commits(self):
        mock_conn, _ = _make_mock_conn(fetchone=(1,))
        db.create_user(mock_conn, "aditi", "hashed-pw")
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# get_user_by_username
# ---------------------------------------------------------------------------

class TestGetUserByUsername:
    def test_returns_dict_when_found(self):
        mock_conn, _ = _make_mock_conn(fetchone=(3, "aditi", "hashed-pw", "user"))
        result = db.get_user_by_username(mock_conn, "aditi")
        assert result == {"id": 3, "username": "aditi", "password_hash": "hashed-pw", "role": "user"}

    def test_returns_none_when_not_found(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        assert db.get_user_by_username(mock_conn, "nobody") is None


# ---------------------------------------------------------------------------
# username_exists
# ---------------------------------------------------------------------------

class TestUsernameExists:
    def test_returns_true_when_row_found(self):
        mock_conn, _ = _make_mock_conn(fetchone=(1,))
        assert db.username_exists(mock_conn, "aditi") is True

    def test_returns_false_when_not_found(self):
        mock_conn, _ = _make_mock_conn(fetchone=None)
        assert db.username_exists(mock_conn, "nobody") is False


# ---------------------------------------------------------------------------
# Cadence-A series helpers + shared mirror sync
# ---------------------------------------------------------------------------

class TestSeriesHelpers:
    def _rows(self, n, amount=1200.0):
        from datetime import date
        return [{"id": 100 + i, "entry_date": db.add_months(date(2026, 5, 1), i), "share_ratio": 1.0,
                 "amount": amount, "entry_text": "Ins", "merchant": "Acme"} for i in range(n)]

    def test_add_months_wraps_year(self):
        from datetime import date
        assert db.add_months(date(2026, 11, 15), 3) == date(2027, 2, 1)

    def test_get_series_info_none_without_series(self):
        conn, _ = _make_mock_conn(fetchone=None)
        assert db.get_series_info(conn, 1) is None

    def test_respread_grows_beyond_twelve_without_cap(self):
        from datetime import date
        conn, _ = _make_mock_conn()
        rows = [{"id": 1, "entry_date": date(2026, 5, 1), "share_ratio": 1.0}]
        inserted = []
        def fake_insert(c, d, *a, **k):
            inserted.append((d, k["divide_by"], k["monthly_amount"], k["series_id"], k["merchant"]))
            return 100 + len(inserted)
        with patch("db.get_series_rows", return_value=rows), \
             patch("db.insert_data_feed_row", side_effect=fake_insert), \
             patch("db._apply_series_amounts") as apply_amounts, \
             patch("db.sync_shared_from_history") as sync:
            out = db.respread_series(conn, "s1", 1400.0, 14, {
                "keep_id": 1, "entry_date": date(2026, 5, 1), "entry_text": "Ins", "merchant": "Acme",
                "category": "Bills", "sub_category": "Ins", "spend_type": "Expense",
                "shared_expense": "N", "share_ratio": 1.0})
        assert len(out["created"]) == 13 and out["deleted"] == []
        assert inserted[0][0] == date(2026, 6, 1) and inserted[-1][0] == date(2027, 6, 1)
        assert all(i[1] == 14 and i[2] == 100.0 and i[3] == "s1" and i[4] == "Acme" for i in inserted)
        assert apply_amounts.call_args[0][2:] == (1400.0, 14)
        assert sync.call_count == 14  # every month's shared mirror re-synced

    def test_respread_shrinks_from_the_end(self):
        conn, cur = _make_mock_conn()
        rows = self._rows(12)
        with patch("db.get_series_rows", return_value=rows), \
             patch("db._apply_series_amounts"), patch("db.sync_shared_from_history"):
            out = db.respread_series(conn, "s1", 1200.0, 10, {"keep_id": 100, "share_ratio": 1.0})
        assert out["deleted"] == [110, 111]

    def test_respread_refuses_to_delete_the_edited_row(self):
        conn, _ = _make_mock_conn()
        with patch("db.get_series_rows", return_value=self._rows(12)):
            with pytest.raises(ValueError):
                db.respread_series(conn, "s1", 1200.0, 10, {"keep_id": 111, "share_ratio": 1.0})

    def test_remove_row_recalculates_remaining_over_new_count(self):
        conn, _ = _make_mock_conn()
        rows = self._rows(12)
        with patch("db.get_series_rows", return_value=rows), \
             patch("db.delete_history_row") as delete_row, \
             patch("db._apply_series_amounts") as apply_amounts, \
             patch("db.sync_shared_from_history") as sync:
            left = db.remove_series_row_and_recalc(conn, 105, "s1")
        assert left == 11
        delete_row.assert_called_once_with(conn, 105)
        remaining, amount, divide_by = apply_amounts.call_args[0][1:]
        assert amount == 1200.0 and divide_by == 11 and 105 not in [r["id"] for r in remaining]
        assert sync.call_count == 11


class TestSyncSharedFromHistory:
    # (entry_date, merchant, category, sub_category, entry_text, amount, monthly_amount, share_ratio, shared_expense)
    def _row(self, shared="Y", d=None):
        from datetime import date
        return (d or date(2026, 6, 1), "Acme", "Bills", "Ins", "Ins", 1200, 100, 0.7, shared)

    def test_shared_row_is_upserted_with_merchant(self):
        conn, _ = _make_mock_conn(fetchone=self._row())
        with patch("db.upsert_shared_transaction") as up, patch("db.delete_shared_transaction") as dele:
            db.sync_shared_from_history(conn, 7)
        up.assert_called_once()
        args = up.call_args[0]
        assert args[1:4] == (7, 1200.0, 100.0) and args[6] == "Acme"
        dele.assert_not_called()

    def test_unshared_row_removes_mirror(self):
        conn, _ = _make_mock_conn(fetchone=self._row(shared="N"))
        with patch("db.upsert_shared_transaction") as up, patch("db.delete_shared_transaction") as dele:
            db.sync_shared_from_history(conn, 7)
        up.assert_not_called()
        dele.assert_called_once_with(conn, 7)

    def test_out_of_scope_date_removes_mirror(self):
        from datetime import date
        conn, _ = _make_mock_conn(fetchone=self._row(d=date(2026, 3, 1)))
        with patch("db.upsert_shared_transaction") as up, patch("db.delete_shared_transaction") as dele:
            db.sync_shared_from_history(conn, 7)
        up.assert_not_called()
        dele.assert_called_once()

    def test_missing_history_row_removes_mirror(self):
        conn, _ = _make_mock_conn(fetchone=None)
        with patch("db.delete_shared_transaction") as dele:
            db.sync_shared_from_history(conn, 7)
        dele.assert_called_once_with(conn, 7)


class TestFyMonthTotals:
    def test_builds_apr_to_mar_across_year_boundary_and_zero_fills(self):
        conn, cur = _make_mock_conn(fetchall=[("Apr-2026", Decimal("100.50"), 3), ("Jan-2027", Decimal("40"), 1)])
        out = db.get_fy_month_totals(conn, 2027)
        assert [m["period"] for m in out["months"]] == [
            "Apr-2026", "May-2026", "Jun-2026", "Jul-2026", "Aug-2026", "Sep-2026",
            "Oct-2026", "Nov-2026", "Dec-2026", "Jan-2027", "Feb-2027", "Mar-2027",
        ]
        assert out["label"] == "FY27" and out["fy"] == 2027
        assert out["months"][0]["total"] == 100.5 and out["months"][0]["count"] == 3
        assert out["months"][1]["total"] == 0.0 and out["months"][1]["count"] == 0
        assert out["months"][9]["month"] == "Jan"
        assert out["fy_total"] == 140.5
        assert cur.execute.call_args[0][1][0][0] == "Apr-2026"

    def test_fy25_starts_in_2024(self):
        conn, _ = _make_mock_conn(fetchall=[])
        out = db.get_fy_month_totals(conn, 2025)
        assert out["months"][0]["period"] == "Apr-2024" and out["months"][-1]["period"] == "Mar-2025"
        assert out["label"] == "FY25" and out["fy_total"] == 0
