"""
Tests for pure utility functions in categorizer/models/train.py.

Covers: build_amount_features, _to_onehot, _resolve_column.
No ML training is performed — these are all pure NumPy/pandas functions.
"""

import numpy as np
import pandas as pd
import pytest

from models.train import _resolve_column, _to_onehot, build_amount_features


class TestBuildAmountFeatures:
    def test_output_shape(self):
        # 4 inputs → (4, 5): 1 log-amount col + 4 one-hot bin cols
        result = build_amount_features([0.0, 100.0, 500.0, 2000.0])
        assert result.shape == (4, 5)

    def test_zero_amount_log_column_is_zero(self):
        dense = build_amount_features([0.0]).toarray()
        assert dense[0, 0] == pytest.approx(0.0)  # log(1 + 0) = 0

    def test_large_amount_falls_in_last_bin(self):
        # 2000 → np.digitize([2000], [100, 500, 2000]) = [3] → column index 4
        dense = build_amount_features([2000.0]).toarray()
        assert dense[0, 4] == pytest.approx(1.0)

    def test_negative_amount_log_equals_positive(self):
        # Uses abs() before log, so −100 and +100 produce the same log value
        pos = build_amount_features([100.0]).toarray()
        neg = build_amount_features([-100.0]).toarray()
        assert pos[0, 0] == pytest.approx(neg[0, 0])

    def test_nan_amount_treated_as_zero(self):
        dense = build_amount_features([float("nan")]).toarray()
        assert dense[0, 0] == pytest.approx(0.0)  # log(1 + 0) = 0


class TestToOnehot:
    def test_single_label_correct_position(self):
        classes = np.array(["A", "B", "C"])
        result = _to_onehot(["B"], classes)
        assert result.shape == (1, 3)
        np.testing.assert_array_equal(result[0], [0.0, 1.0, 0.0])

    def test_multiple_labels(self):
        classes = np.array(["X", "Y"])
        result = _to_onehot(["Y", "X"], classes)
        np.testing.assert_array_equal(result[0], [0.0, 1.0])
        np.testing.assert_array_equal(result[1], [1.0, 0.0])

    def test_unknown_label_produces_zero_row(self):
        classes = np.array(["A", "B"])
        result = _to_onehot(["Z"], classes)
        np.testing.assert_array_equal(result[0], [0.0, 0.0])


class TestResolveColumn:
    def test_first_candidate_returned_when_present(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        assert _resolve_column(df, ["a", "b"]) == "a"

    def test_fallback_to_second_candidate(self):
        df = pd.DataFrame({"b": [1], "c": [2]})
        assert _resolve_column(df, ["a", "b"]) == "b"

    def test_raises_when_no_candidate_found(self):
        df = pd.DataFrame({"x": [1]})
        with pytest.raises(ValueError, match="Missing required column"):
            _resolve_column(df, ["a", "b"])
