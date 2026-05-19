import pytest
from processing.rules import apply_rules

RULES = {
    "swiggy": {"category": "Food", "subcategory": "Delivery", "type": "expense", "confidence": 0.9},
    "uber": {"category": "Transport", "subcategory": "Auto", "type": "expense", "confidence": 0.85},
    "uber eats": {"category": "Food", "subcategory": "Delivery", "type": "expense", "confidence": 0.9},
    "netflix": {"category": "Entertainment", "subcategory": "Streaming", "type": "expense", "confidence": 0.9},
}


class TestApplyRules:
    def test_matching_keyword_returns_category(self):
        result = apply_rules("swiggy food delivery", RULES)
        assert result["category"] == "Food"
        assert result["subcategory"] == "Delivery"

    def test_no_match_returns_none(self):
        assert apply_rules("amazon shopping", RULES) is None

    def test_none_text_returns_none(self):
        assert apply_rules(None, RULES) is None

    def test_case_insensitive_match(self):
        result = apply_rules("NETFLIX subscription", RULES)
        assert result is not None
        assert result["category"] == "Entertainment"

    def test_type_is_title_cased(self):
        result = apply_rules("netflix streaming", RULES)
        assert result["type"] == "Expense"

    def test_longer_keyword_wins_over_shorter(self):
        # "uber eats" is longer than "uber" — should match "uber eats" rule
        result = apply_rules("uber eats delivery", RULES)
        assert result["category"] == "Food"
        assert result["subcategory"] == "Delivery"

    def test_matched_keyword_returned(self):
        result = apply_rules("swiggy order", RULES)
        assert "matched_keyword" in result
        assert result["matched_keyword"] == "swiggy"

    def test_confidence_returned(self):
        result = apply_rules("swiggy order", RULES)
        assert result["confidence"] == pytest.approx(0.9)

    def test_empty_rules_returns_none(self):
        assert apply_rules("swiggy order", {}) is None


class TestUberAmountOverride:
    def test_uber_above_150_sets_subcategory_cab(self):
        result = apply_rules("uber ride", RULES, amount=200)
        assert result["subcategory"] == "Cab"

    def test_uber_exactly_150_stays_auto(self):
        result = apply_rules("uber ride", RULES, amount=150)
        assert result["subcategory"] == "Auto"

    def test_uber_below_150_stays_auto(self):
        result = apply_rules("uber ride", RULES, amount=100)
        assert result["subcategory"] == "Auto"

    def test_uber_no_amount_stays_auto(self):
        result = apply_rules("uber ride", RULES, amount=None)
        assert result["subcategory"] == "Auto"

    def test_non_uber_not_affected_by_amount(self):
        result = apply_rules("swiggy delivery", RULES, amount=500)
        assert result["subcategory"] == "Delivery"
