from processing.memory import MerchantMemory


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
