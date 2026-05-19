from processing.cleaner import clean_entry, extract_vpa_handle


class TestCleanEntry:
    def test_lowercases(self):
        assert clean_entry("SWIGGY Payment") == "swiggy payment"

    def test_strips_numbers(self):
        assert clean_entry("UPI 123456") == "upi"

    def test_removes_special_chars(self):
        assert clean_entry("swiggy@upi!") == "swiggy upi"

    def test_collapses_whitespace(self):
        assert clean_entry("foo   bar") == "foo bar"

    def test_strips_leading_trailing_whitespace(self):
        assert clean_entry("  foo  ") == "foo"

    def test_none_returns_empty_string(self):
        assert clean_entry(None) == ""

    def test_empty_string_returns_empty_string(self):
        assert clean_entry("") == ""

    def test_already_clean_passthrough(self):
        assert clean_entry("swiggy") == "swiggy"

    def test_mixed_numbers_and_words(self):
        result = clean_entry("zomato 9876")
        assert "zomato" in result
        assert "9876" not in result


class TestExtractVpaHandle:
    def test_merchant_vpa_returns_handle(self):
        assert extract_vpa_handle("swiggy.bng@icici") == "swiggy bng"

    def test_phone_number_handle_returns_empty(self):
        assert extract_vpa_handle("9876543210@upi") == ""

    def test_no_at_sign_returns_empty(self):
        assert extract_vpa_handle("swiggyupi") == ""

    def test_empty_string_returns_empty(self):
        assert extract_vpa_handle("") == ""

    def test_none_returns_empty(self):
        assert extract_vpa_handle(None) == ""

    def test_dots_become_spaces(self):
        assert extract_vpa_handle("swiggy.order@ybl") == "swiggy order"

    def test_dashes_become_spaces(self):
        assert extract_vpa_handle("big-basket@razorpay") == "big basket"

    def test_underscores_become_spaces(self):
        assert extract_vpa_handle("amazon_pay@apl") == "amazon pay"

    def test_handle_with_digits_is_p2p_returns_empty(self):
        assert extract_vpa_handle("user123@okaxis") == ""

    def test_empty_handle_before_at_returns_empty(self):
        assert extract_vpa_handle("@paytm") == ""

    def test_lowercases_output(self):
        result = extract_vpa_handle("Zomato@icici")
        assert result == result.lower()
