from processing.merchant import extract_merchant


class TestExtractMerchant:
    def test_returns_first_non_stopword_token(self):
        assert extract_merchant("swiggy order food") == "swiggy"

    def test_skips_stopword_payment(self):
        assert extract_merchant("payment swiggy") == "swiggy"

    def test_skips_stopword_upi(self):
        assert extract_merchant("upi zomato") == "zomato"

    def test_skips_stopword_hdfc(self):
        assert extract_merchant("hdfc amazon") == "amazon"

    def test_skips_single_char_tokens(self):
        assert extract_merchant("a swiggy") == "swiggy"

    def test_none_returns_unknown(self):
        assert extract_merchant(None) == "unknown"

    def test_empty_string_returns_unknown(self):
        assert extract_merchant("") == "unknown"

    def test_all_stopwords_returns_unknown(self):
        assert extract_merchant("payment upi transfer neft") == "unknown"

    def test_all_single_chars_returns_unknown(self):
        assert extract_merchant("a b c") == "unknown"

    def test_pos_stopword_skipped(self):
        assert extract_merchant("pos netflix") == "netflix"

    def test_returns_token_as_is(self):
        result = extract_merchant("zomato upi payment")
        assert result == "zomato"

    def test_sbi_stopword_skipped(self):
        assert extract_merchant("sbi netbanking") == "netbanking"
