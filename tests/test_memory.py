import pandas as pd

from processing.memory import MerchantMemory, memory_key


class TestMerchantMemory:
    def test_lookup_empty_returns_none(self):
        m = MerchantMemory()
        assert m.lookup("swiggy") is None

    def test_lookup_after_update_returns_classification(self):
        m = MerchantMemory()
        m.update("swiggy", "Food", "Delivery", "Expense")
        result = m.lookup("swiggy")
        assert result["category"] == "Food"
        assert result["subcategory"] == "Delivery"
        assert result["type"] == "Expense"

    def test_lookup_confidence_is_095(self):
        m = MerchantMemory()
        m.update("swiggy", "Food", "Delivery", "Expense")
        assert m.lookup("swiggy")["confidence"] == 0.95

    def test_update_empty_merchant_is_noop(self):
        m = MerchantMemory()
        m.update("", "Food", "Delivery", "Expense")
        assert m.lookup("") is None

    def test_lookup_empty_merchant_returns_none(self):
        m = MerchantMemory()
        assert m.lookup("") is None

    def test_lookup_none_merchant_returns_none(self):
        m = MerchantMemory()
        assert m.lookup(None) is None

    def test_second_update_overwrites_first(self):
        m = MerchantMemory()
        m.update("swiggy", "Food", "Delivery", "Expense")
        m.update("swiggy", "Transport", "Cab", "Expense")
        result = m.lookup("swiggy")
        assert result["category"] == "Transport"
        assert result["subcategory"] == "Cab"

    def test_multiple_merchants_stored_independently(self):
        m = MerchantMemory()
        m.update("swiggy", "Food", "Delivery", "Expense")
        m.update("uber", "Transport", "Cab", "Expense")
        assert m.lookup("swiggy")["category"] == "Food"
        assert m.lookup("uber")["category"] == "Transport"

    def test_unknown_merchant_returns_none_after_other_updates(self):
        m = MerchantMemory()
        m.update("swiggy", "Food", "Delivery", "Expense")
        assert m.lookup("zomato") is None


def _history(rows):
    return pd.DataFrame(rows, columns=["vpa", "db_merchant", "final_category", "final_subcategory", "final_type"])


class TestMemoryKey:
    def test_vpa_preferred_and_lowercased(self):
        assert memory_key(" Q289@YBL ", "S P PRAKASH") == "vpa:q289@ybl"

    def test_falls_back_to_normalised_merchant(self):
        assert memory_key("", "  s p   prakash ") == "merchant:S P PRAKASH"

    def test_empty_when_nothing_known(self):
        assert memory_key(None, "") == ""


class TestFromHistory:
    def test_consistent_payee_is_remembered(self):
        m = MerchantMemory.from_history(_history([
            ("a@ybl", "A", "Food", "Eating Out", "Expense"),
        ] * 4 + [("a@ybl", "A", "Travel", "Auto", "Expense")]))
        hit = m.lookup("vpa:a@ybl")
        assert (hit["category"], hit["subcategory"], hit["type"]) == ("Food", "Eating Out", "Expense")
        assert hit["confidence"] == 0.8

    def test_single_row_payee_is_skipped(self):
        m = MerchantMemory.from_history(_history([("a@ybl", "A", "Food", "Eating Out", "Expense")]))
        assert m.lookup("vpa:a@ybl") is None

    def test_payee_below_80_percent_agreement_is_skipped(self):
        m = MerchantMemory.from_history(_history([
            ("a@ybl", "A", "Food", "Eating Out", "Expense"),
            ("a@ybl", "A", "Food", "Eating Out", "Expense"),
            ("a@ybl", "A", "Travel", "Auto", "Expense"),
        ]))
        assert m.lookup("vpa:a@ybl") is None

    def test_rows_without_payee_or_category_are_ignored(self):
        m = MerchantMemory.from_history(_history([
            ("", "", "Food", "Eating Out", "Expense"),
            ("", "", "Food", "Eating Out", "Expense"),
            ("b@ybl", "B", "", "", ""),
            ("b@ybl", "B", "", "", ""),
        ]))
        assert m.memory == {}

    def test_merchant_name_used_when_no_vpa(self):
        m = MerchantMemory.from_history(_history([("", "Netflix", "Bills", "OTT", "Expense")] * 2))
        assert m.lookup("merchant:NETFLIX")["category"] == "Bills"
