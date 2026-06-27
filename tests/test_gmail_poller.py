import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import gmail_poller
from gmail_poller import _strip_html, _get_received_at, _get_subject, run_parser_tests, run_categorization, send_summary_email


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


class TestRunParserTests:
    def test_sets_cwd_to_loader_directory(self):
        mock_result = MagicMock()
        mock_result.stdout = "PASS  all"
        mock_result.stderr = ""
        with patch("gmail_poller.subprocess.run", return_value=mock_result) as mock_run:
            run_parser_tests()
        _, kwargs = mock_run.call_args
        expected_cwd = os.path.dirname(os.path.abspath(gmail_poller.__file__))
        assert kwargs["cwd"] == expected_cwd

    def test_returns_stdout_on_success(self):
        mock_result = MagicMock()
        mock_result.stdout = "PASS  upi_debit\nPASS  upi_credit"
        mock_result.stderr = ""
        with patch("gmail_poller.subprocess.run", return_value=mock_result):
            output = run_parser_tests()
        assert "PASS  upi_debit" in output
        assert "PASS  upi_credit" in output

    def test_returns_stderr_on_failure(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "can't open file '/app/parser.py': [Errno 2] No such file or directory"
        with patch("gmail_poller.subprocess.run", return_value=mock_result):
            output = run_parser_tests()
        assert "can't open file" in output

    def test_combines_stdout_and_stderr(self):
        mock_result = MagicMock()
        mock_result.stdout = "PASS  test1"
        mock_result.stderr = "FAIL  test2"
        with patch("gmail_poller.subprocess.run", return_value=mock_result):
            output = run_parser_tests()
        assert "PASS  test1" in output
        assert "FAIL  test2" in output

    def test_uses_current_python_executable(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("gmail_poller.subprocess.run", return_value=mock_result) as mock_run:
            run_parser_tests()
        args, _ = mock_run.call_args
        assert args[0][0] == sys.executable
        assert args[0][1] == "parser.py"


class TestRunCategorization:
    def _mock_batch_process(self, side_effect=None):
        mock_module = MagicMock()
        if side_effect:
            mock_module.cmd_process.side_effect = side_effect
        return mock_module

    def test_returns_ok_on_success(self):
        mock_module = self._mock_batch_process()
        with patch.dict(sys.modules, {"batch_process": mock_module}):
            result = run_categorization()
        assert result == "ok"

    def test_calls_cmd_process(self):
        mock_module = self._mock_batch_process()
        with patch.dict(sys.modules, {"batch_process": mock_module}):
            run_categorization()
        mock_module.cmd_process.assert_called_once()

    def test_returns_failed_string_on_exception(self):
        mock_module = self._mock_batch_process(side_effect=RuntimeError("GCS bucket not found"))
        with patch.dict(sys.modules, {"batch_process": mock_module}):
            result = run_categorization()
        assert result.startswith("FAILED:")
        assert "GCS bucket not found" in result

    def test_does_not_raise_on_exception(self):
        mock_module = self._mock_batch_process(side_effect=KeyError("GCS_MODEL_BUCKET"))
        with patch.dict(sys.modules, {"batch_process": mock_module}):
            result = run_categorization()
        assert "FAILED" in result


class TestSendSummaryEmail:
    def _make_service(self):
        # Use a plain MagicMock — don't call send() during setup or it poisons call counts
        return MagicMock()

    def _make_summary(self, processed=0, skipped=0, failed=0, transactions=None):
        return {
            "processed": processed,
            "skipped": skipped,
            "failed": failed,
            "transactions": transactions or [],
        }

    def _decode_email(self, svc):
        """Parse the MIME message captured by the mock and return (subject_str, body_str)."""
        import base64
        import email as email_lib
        call_kwargs = svc.users().messages().send.call_args
        raw = call_kwargs[1]["body"]["raw"]
        mime_bytes = base64.urlsafe_b64decode(raw)
        msg_obj = email_lib.message_from_bytes(mime_bytes)
        parts = email_lib.header.decode_header(msg_obj["subject"])
        subject = "".join(
            p.decode(enc or "utf-8") if isinstance(p, bytes) else p
            for p, enc in parts
        )
        payload = msg_obj.get_payload()
        # MIMEText with non-ASCII produces a base64 payload; plain ASCII stays as-is
        try:
            body = base64.b64decode(payload).decode("utf-8")
        except Exception:
            body = payload
        return subject, body

    def test_no_notification_email_skips_send(self, monkeypatch):
        monkeypatch.delenv("NOTIFICATION_EMAIL", raising=False)
        svc = self._make_service()
        send_summary_email(svc, self._make_summary(), "(no output)")
        svc.users().messages().send.assert_not_called()

    def test_sends_when_notification_email_set(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        svc = self._make_service()
        send_summary_email(svc, self._make_summary(processed=1, transactions=[{
            "date": datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
            "format": "upi", "type": "debit", "amount": 100.0, "merchant": "Swiggy",
        }]), "PASS  all")
        svc.users().messages().send.assert_called_once()

    def test_subject_contains_date(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        svc = self._make_service()
        send_summary_email(svc, self._make_summary(), "(no output)")
        subject, _ = self._decode_email(svc)
        assert "2026" in subject or "May" in subject

    def test_no_transactions_subject_says_no_transactions(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        svc = self._make_service()
        send_summary_email(svc, self._make_summary(processed=0, skipped=0, failed=0), "(no output)")
        subject, _ = self._decode_email(svc)
        assert "No Transactions" in subject

    def test_categorization_status_in_email_body(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        svc = self._make_service()
        send_summary_email(svc, self._make_summary(), "(no output)", categorization_status="FAILED: GCS down")
        _, body = self._decode_email(svc)
        assert "FAILED: GCS down" in body

    def test_categorization_ok_in_email_body(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        svc = self._make_service()
        send_summary_email(svc, self._make_summary(), "PASS  all tests", categorization_status="ok")
        _, body = self._decode_email(svc)
        assert "ok" in body
        assert "PASS  all tests" in body

    def test_failed_details_appear_in_body(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        svc = self._make_service()
        summary = self._make_summary(failed=2)
        summary["failed_details"] = [
            {"id": "abc123", "reason": "empty body"},
            {"id": "def456", "reason": "unexpected error: ValueError: bad data",
             "snippet": "Rs. 100 debit"},
        ]
        send_summary_email(svc, summary, "(no output)")
        _, body = self._decode_email(svc)
        assert "Failed Messages (2)" in body
        assert "id=abc123" in body
        assert "empty body" in body
        assert "id=def456" in body
        assert "unexpected error: ValueError: bad data" in body
        assert "(Rs. 100 debit)" in body

    def test_skipped_details_appear_in_body(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        svc = self._make_service()
        summary = self._make_summary(skipped=2)
        summary["skipped_details"] = [
            {"id": "ghi789", "reason": "already processed",
             "merchant": "Swiggy", "amount": 350.0, "txn_type": "debit"},
            {"id": "jkl012", "reason": "duplicate of mno345"},
        ]
        send_summary_email(svc, summary, "(no output)")
        _, body = self._decode_email(svc)
        assert "Skipped Messages (2)" in body
        assert "id=ghi789" in body
        assert "already processed" in body
        assert "Swiggy" in body
        assert "350.00" in body
        assert "debit" in body
        assert "id=jkl012" in body
        assert "duplicate of mno345" in body

    def test_missing_detail_keys_backward_compat(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        svc = self._make_service()
        # Old-style summary dict without failed_details / skipped_details
        summary = self._make_summary(failed=1, skipped=1)
        send_summary_email(svc, summary, "(no output)")
        _, body = self._decode_email(svc)
        assert "Failed Messages" not in body
        assert "Skipped Messages" not in body
