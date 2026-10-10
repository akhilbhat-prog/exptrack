"""Tests for categorizer/models/predict.py — stage-to-stage conditioning."""
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from models.predict import predict_category


class _StubModel:
    def __init__(self, classes, probs):
        self.classes_ = np.array(classes)
        self._probs = np.array(probs)
        self.last_input = None

    def predict_proba(self, X):
        self.last_input = X.toarray()
        return self._probs.reshape(1, -1)


def _bundle(type_probs, cat_probs):
    texts = ["swiggy food order", "lic premium"]
    return {
        "word_vec": TfidfVectorizer(analyzer="word").fit(texts),
        "char_vec": TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit(texts),
        "type_model": _StubModel(["Expense", "Investment"], type_probs),
        "cat_model": _StubModel(["Food", "Insurance"], cat_probs),
        "subcat_model": _StubModel(["Eating Out", "LIC"], [0.8, 0.2]),
    }


def test_category_stage_receives_one_hot_type_not_probabilities():
    bundle = _bundle([0.97, 0.03], [0.9, 0.1])
    predict_category(bundle, "swiggy food order", 250.0)
    assert bundle["cat_model"].last_input[0, -2:].tolist() == [1.0, 0.0]


def test_subcategory_stage_receives_one_hot_type_and_category():
    bundle = _bundle([0.97, 0.03], [0.6, 0.4])
    predict_category(bundle, "swiggy food order", 250.0)
    assert bundle["subcat_model"].last_input[0, -4:].tolist() == [1.0, 0.0, 1.0, 0.0]


def test_confidence_still_uses_probabilities():
    bundle = _bundle([0.97, 0.03], [0.9, 0.1])
    result = predict_category(bundle, "swiggy food order", 250.0)
    assert result["category"] == "Food"
    assert result["confidence"] == 0.2 * 0.97 + 0.3 * 0.9 + 0.5 * 0.8
