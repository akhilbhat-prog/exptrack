"""
Tests for categorizer/processing/pipeline.py.

Covers: build_combined_text, predict_row, process_dataframe.
ML model and external calls are mocked where needed.
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from processing.memory import MerchantMemory
from processing.pipeline import build_combined_text, predict_row, process_dataframe


class TestBuildCombinedText:
    def test_no_vpa_returns_entry_text(self):
        assert build_combined_text("zomato food", "") == "zomato food"

    def test_vpa_handle_appended(self):
        # extract_vpa_handle("merchant@paytm") → "merchant"
        result = build_combined_text("food order", "merchant@paytm")
        assert "food order" in result
        assert "merchant" in result

    def test_phone_number_vpa_ignored(self):
        # extract_vpa_handle strips pure-digit handles (phone numbers)
        result = build_combined_text("food order", "9876543210@upi")
        assert result == "food order"


class TestPredictRow:
    def _memory(self, lookup_return=None):
        m = MagicMock(spec=MerchantMemory)
        m.lookup.return_value = lookup_return
        return m

    def test_memory_hit_returns_memory_source(self):
        cached = {
            "category": "Food",
            "subcategory": "Eating Out",
            "type": "Expense",
            "confidence": 0.95,
        }
        memory = self._memory(lookup_return=cached)
        result = predict_row(
            {"merchant": "ZOMATO", "text_combined": "zomato food", "amount": 200},
            rules={},
            memory=memory,
        )
        assert result["source"] == "memory"
        assert result["category"] == "Food"
        assert result["confidence"] == pytest.approx(0.95)

    def test_rules_hit_returns_rule_source(self):
        memory = self._memory(lookup_return=None)
        rule_result = {
            "category": "Transport",
            "subcategory": "Cab",
            "type": "Expense",
            "confidence": 0.9,
        }
        with patch("processing.pipeline.apply_rules", return_value=rule_result):
            result = predict_row(
                {"merchant": "UBER", "text_combined": "uber ride", "amount": 200},
                rules={},
                memory=memory,
            )
        assert result["source"] == "rule"
        assert result["category"] == "Transport"

    def test_ml_model_used_when_no_memory_or_rules(self):
        memory = self._memory(lookup_return=None)
        ml_result = {
            "category": "Shopping",
            "subcategory": "Online",
            "type": "Expense",
            "confidence": 0.8,
        }
        with patch("processing.pipeline.apply_rules", return_value=None), \
             patch("processing.pipeline.predict_category", return_value=ml_result):
            result = predict_row(
                {"merchant": "AMAZON", "text_combined": "amazon shopping", "amount": 500},
                rules={},
                memory=memory,
                model=object(),  # non-None triggers ML path
            )
        assert result["source"] == "ml"
        assert result["category"] == "Shopping"

    def test_no_model_and_no_match_returns_unknown(self):
        memory = self._memory(lookup_return=None)
        with patch("processing.pipeline.apply_rules", return_value=None):
            result = predict_row(
                {"merchant": "XYZUNKNOWN", "text_combined": "xyzunknown", "amount": 100},
                rules={},
                memory=memory,
                model=None,
            )
        assert result["source"] == "none"
        assert result["category"] == "Unknown"
        assert result["confidence"] == pytest.approx(0.0)


class TestProcessDataframe:
    def _input_df(self):
        return pd.DataFrame([
            {"entry_raw": "ZOMATO FOOD ORDER", "vpa": "zomato@paytm", "amount": 200.0},
            {"entry_raw": "UBER RIDE", "vpa": "", "amount": 150.0},
        ])

    def _fake_predict(self, row, **kwargs):
        return {
            "category": "Food",
            "subcategory": "Eating Out",
            "type": "Expense",
            "confidence": 0.9,
            "source": "rule",
        }

    def test_output_has_prediction_columns(self):
        memory = MagicMock(spec=MerchantMemory)
        with patch("processing.pipeline.predict_row", side_effect=self._fake_predict):
            result = process_dataframe(self._input_df(), rules={}, memory=memory)
        for col in ("pred_category", "pred_subcategory", "pred_type", "prediction_source", "confidence"):
            assert col in result.columns

    def test_output_has_cleaned_and_merchant_columns(self):
        memory = MagicMock(spec=MerchantMemory)
        with patch("processing.pipeline.predict_row", side_effect=self._fake_predict):
            result = process_dataframe(self._input_df(), rules={}, memory=memory)
        assert "entry_clean" in result.columns
        assert "merchant" in result.columns
        assert "text_combined" in result.columns
        assert len(result) == 2
