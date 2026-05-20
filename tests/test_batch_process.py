"""
Tests for the categorizer batch pipeline (batch_process.py).

All external I/O (GCS, DB) is mocked. No real PostgreSQL or GCS required.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

from batch_process import cmd_process, cmd_complete, BATCH_SIZE


def _make_transactions_df(n: int) -> pd.DataFrame:
    """Minimal DataFrame matching fetch_transactions() output schema."""
    return pd.DataFrame({
        "id": range(n),
        "date": pd.to_datetime(["2026-05-20"] * n),
        "entry_raw": ["Rs.100.00 debited"] * n,
        "amount": [100.0] * n,
        "db_merchant": ["Swiggy"] * n,
        "vpa": [""] * n,
        "upi_ref": [""] * n,
    })


def _make_processed_df(n: int) -> pd.DataFrame:
    """Minimal DataFrame matching process_dataframe() output schema."""
    df = _make_transactions_df(n)
    df["category"] = "Food"
    df["subcategory"] = "Eating Out"
    df["type"] = "Expense"
    df["pred_category"] = "Food"
    df["pred_subcategory"] = "Eating Out"
    df["pred_type"] = "Expense"
    df["pred_confidence"] = 0.9
    df["pred_source"] = "ml"
    return df


@contextmanager
def _mock_connect():
    mock_conn = MagicMock()
    yield mock_conn


class TestCmdProcess:
    def test_returns_early_when_no_transactions(self):
        with patch("batch_process.load_model", return_value=MagicMock()), \
             patch("batch_process.load_rules", return_value={}), \
             patch("batch_process.MerchantMemory", return_value=MagicMock()), \
             patch("batch_process.fetch_transactions", return_value=pd.DataFrame()), \
             patch("batch_process.connect") as mock_connect:
            cmd_process()
        mock_connect.assert_not_called()

    def test_creates_one_batch_for_under_batch_size(self):
        df = _make_transactions_df(18)
        processed = _make_processed_df(18)
        mock_conn = MagicMock()
        with patch("batch_process.load_model", return_value=MagicMock()), \
             patch("batch_process.load_rules", return_value={}), \
             patch("batch_process.MerchantMemory", return_value=MagicMock()), \
             patch("batch_process.fetch_transactions", return_value=df), \
             patch("batch_process.process_dataframe", return_value=processed), \
             patch("batch_process.connect") as mock_connect, \
             patch("batch_process.create_batch", return_value=1) as mock_create, \
             patch("batch_process.insert_batch_items"):
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            cmd_process()
        assert mock_create.call_count == 1

    def test_creates_two_batches_for_over_batch_size(self):
        n = BATCH_SIZE + 5
        df = _make_transactions_df(n)
        processed = _make_processed_df(n)
        mock_conn = MagicMock()
        with patch("batch_process.load_model", return_value=MagicMock()), \
             patch("batch_process.load_rules", return_value={}), \
             patch("batch_process.MerchantMemory", return_value=MagicMock()), \
             patch("batch_process.fetch_transactions", return_value=df), \
             patch("batch_process.process_dataframe", return_value=processed), \
             patch("batch_process.connect") as mock_connect, \
             patch("batch_process.create_batch", return_value=1) as mock_create, \
             patch("batch_process.insert_batch_items"):
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            cmd_process()
        assert mock_create.call_count == 2

    def test_exact_batch_size_creates_one_batch(self):
        df = _make_transactions_df(BATCH_SIZE)
        processed = _make_processed_df(BATCH_SIZE)
        mock_conn = MagicMock()
        with patch("batch_process.load_model", return_value=MagicMock()), \
             patch("batch_process.load_rules", return_value={}), \
             patch("batch_process.MerchantMemory", return_value=MagicMock()), \
             patch("batch_process.fetch_transactions", return_value=df), \
             patch("batch_process.process_dataframe", return_value=processed), \
             patch("batch_process.connect") as mock_connect, \
             patch("batch_process.create_batch", return_value=1) as mock_create, \
             patch("batch_process.insert_batch_items"):
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            cmd_process()
        assert mock_create.call_count == 1

    def test_insert_batch_items_called_once_per_batch(self):
        n = BATCH_SIZE + 5
        df = _make_transactions_df(n)
        processed = _make_processed_df(n)
        mock_conn = MagicMock()
        with patch("batch_process.load_model", return_value=MagicMock()), \
             patch("batch_process.load_rules", return_value={}), \
             patch("batch_process.MerchantMemory", return_value=MagicMock()), \
             patch("batch_process.fetch_transactions", return_value=df), \
             patch("batch_process.process_dataframe", return_value=processed), \
             patch("batch_process.connect") as mock_connect, \
             patch("batch_process.create_batch", return_value=1), \
             patch("batch_process.insert_batch_items") as mock_insert:
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            cmd_process()
        assert mock_insert.call_count == 2

    def test_model_load_failure_propagates(self):
        with patch("batch_process.load_model", side_effect=FileNotFoundError("No champion model")), \
             patch("batch_process.load_rules", return_value={}), \
             patch("batch_process.MerchantMemory", return_value=MagicMock()):
            with pytest.raises(FileNotFoundError, match="No champion model"):
                cmd_process()

    def test_process_dataframe_called_with_all_transactions(self):
        df = _make_transactions_df(5)
        processed = _make_processed_df(5)
        mock_conn = MagicMock()
        with patch("batch_process.load_model", return_value=MagicMock()), \
             patch("batch_process.load_rules", return_value={}), \
             patch("batch_process.MerchantMemory", return_value=MagicMock()), \
             patch("batch_process.fetch_transactions", return_value=df), \
             patch("batch_process.process_dataframe", return_value=processed) as mock_proc, \
             patch("batch_process.connect") as mock_connect, \
             patch("batch_process.create_batch", return_value=1), \
             patch("batch_process.insert_batch_items"):
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            cmd_process()
        assert mock_proc.call_count == 1
        called_df = mock_proc.call_args[0][0]
        assert len(called_df) == 5


class TestCmdComplete:
    def test_calls_complete_batch(self):
        mock_conn = MagicMock()
        with patch("batch_process.connect") as mock_connect, \
             patch("batch_process.complete_batch", return_value=5) as mock_complete, \
             patch("batch_process.parse_database", return_value=pd.DataFrame({"entry_raw": ["test"]})), \
             patch("batch_process.train_category_model", return_value=MagicMock()), \
             patch("batch_process.register_model"), \
             patch("batch_process.clean_entry", side_effect=lambda x: x):
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            cmd_complete(batch_id=7)
        mock_complete.assert_called_once_with(mock_conn, 7)

    def test_triggers_model_retraining_after_complete(self):
        mock_conn = MagicMock()
        with patch("batch_process.connect") as mock_connect, \
             patch("batch_process.complete_batch", return_value=5), \
             patch("batch_process.parse_database", return_value=pd.DataFrame({"entry_raw": ["test"]})), \
             patch("batch_process.train_category_model", return_value=MagicMock()) as mock_train, \
             patch("batch_process.register_model") as mock_register, \
             patch("batch_process.clean_entry", side_effect=lambda x: x):
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            cmd_complete(batch_id=7)
        mock_train.assert_called_once()
        mock_register.assert_called_once()

    def test_complete_batch_value_error_exits(self):
        mock_conn = MagicMock()
        with patch("batch_process.connect") as mock_connect, \
             patch("batch_process.complete_batch", side_effect=ValueError("Batch not reviewed")):
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(SystemExit):
                cmd_complete(batch_id=99)
