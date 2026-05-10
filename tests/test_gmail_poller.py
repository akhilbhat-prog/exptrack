from datetime import datetime, timezone

from gmail_poller import _strip_html, _get_received_at, _get_subject


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>Hello</p>") == "Hello"

    def test_skips_style_content(self):
        assert _strip_html("<style>body { color: red; }</style>Hello") == "Hello"

    def test_skips_script_content(self):
        assert _strip_html("<script>alert('x')</script>World") == "World"

    def test_block_tags_produce_space(self):
        result = _strip_html("<div>foo</div><div>bar</div>")
        assert "foo" in result and "bar" in result

    def test_decodes_html_entities(self):
        result = _strip_html("Rs.&nbsp;299.00 &amp; more")
        assert "299.00" in result
        assert "&" in result

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_plain_text_passthrough(self):
        assert _strip_html("no tags here") == "no tags here"

    def test_nested_skip_tags(self):
        # Content inside nested style blocks should also be skipped
        result = _strip_html("<style><style>inner</style></style>visible")
        assert "inner" not in result
        assert "visible" in result


class TestGetReceivedAt:
    def test_string_ms_to_utc(self):
        msg = {"internalDate": "1714298400000"}
        dt = _get_received_at(msg)
        assert dt.tzinfo == timezone.utc
        assert dt == datetime.fromtimestamp(1714298400, tz=timezone.utc)

    def test_integer_ms_to_utc(self):
        msg = {"internalDate": 1714298400000}
        dt = _get_received_at(msg)
        assert dt.tzinfo == timezone.utc
        assert dt == datetime.fromtimestamp(1714298400, tz=timezone.utc)

    def test_missing_internal_date_returns_utc(self):
        dt = _get_received_at({})
        assert dt.tzinfo == timezone.utc
        assert isinstance(dt, datetime)


class TestGetSubject:
    def test_returns_subject_header(self):
        msg = {"payload": {"headers": [{"name": "Subject", "value": "HDFC Alert"}]}}
        assert _get_subject(msg) == "HDFC Alert"

    def test_case_insensitive_header_name(self):
        msg = {"payload": {"headers": [{"name": "subject", "value": "Test"}]}}
        assert _get_subject(msg) == "Test"

    def test_no_subject_header_returns_default(self):
        msg = {"payload": {"headers": [{"name": "From", "value": "bank@example.com"}]}}
        assert _get_subject(msg) == "(no subject)"

    def test_empty_payload_returns_default(self):
        assert _get_subject({}) == "(no subject)"

    def test_empty_headers_returns_default(self):
        assert _get_subject({"payload": {"headers": []}}) == "(no subject)"
