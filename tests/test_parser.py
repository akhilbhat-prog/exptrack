from datetime import datetime, timezone, timedelta
import parser as email_parser
from parser import (
    _parse_amount,
    _parse_date_ddmmyy,
    _merge_date_time,
    _parse_date_debit_card,
    is_upi_debit,
    is_upi_credit,
    is_netbanking,
    is_debit_card,
)

IST = timezone(timedelta(hours=5, minutes=30))
RECEIVED = datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_parse_amount_plain():
    assert _parse_amount("70.00") == 70.00

def test_parse_amount_indian_commas():
    assert _parse_amount("1,00,000.00") == 100000.00

def test_parse_amount_thousands():
    assert _parse_amount("12,015.00") == 12015.00

def test_parse_date_ddmmyy_returns_utc():
    dt = _parse_date_ddmmyy("28-04-26")
    assert dt.tzinfo == timezone.utc

def test_parse_date_ddmmyy_correct_value():
    dt = _parse_date_ddmmyy("28-04-26")
    # Midnight IST = 18:30 UTC previous day
    assert dt == datetime(2026, 4, 27, 18, 30, 0, tzinfo=timezone.utc)

def test_merge_date_time_same_ist_date_uses_received():
    # body_date: 28 Apr 2026 IST, received_at: 28 Apr 2026 10:00 UTC (= 15:30 IST)
    body_date = _parse_date_ddmmyy("28-04-26")
    result = _merge_date_time(body_date, RECEIVED)
    assert result == RECEIVED

def test_merge_date_time_different_ist_date_uses_body():
    # Simulate a delayed email: body says 27 Apr, received 28 Apr
    body_date = _parse_date_ddmmyy("27-04-26")
    result = _merge_date_time(body_date, RECEIVED)
    assert result == body_date

def test_parse_date_debit_card_converts_to_utc():
    dt = _parse_date_debit_card("05 Apr, 2026", "15:23:09")
    # 15:23:09 IST - 5:30 = 09:53:09 UTC
    assert dt == datetime(2026, 4, 5, 9, 53, 9, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Format detection predicates
# ---------------------------------------------------------------------------

def test_is_upi_debit_old_format():
    assert is_upi_debit("has been debited from account 1750 to VPA")

def test_is_upi_debit_new_format():
    assert is_upi_debit("is debited from your account ending 1750 towards VPA")

def test_is_upi_credit():
    assert is_upi_credit("is successfully credited to your account")

def test_is_netbanking():
    assert is_netbanking("HDFC Bank NetBanking for payment")

def test_is_debit_card():
    assert is_debit_card("is debited from your HDFC Bank Debit Card ending")

def test_predicates_do_not_cross_match():
    upi_debit_body = "has been debited from account 1750 to VPA"
    assert not is_upi_credit(upi_debit_body)
    assert not is_netbanking(upi_debit_body)
    assert not is_debit_card(upi_debit_body)

# ---------------------------------------------------------------------------
# Format 1: UPI Debit (old format)
# ---------------------------------------------------------------------------

UPI_DEBIT_OLD = (
    "Dear Customer, Rs.70.00 has been debited from account 1750 to VPA "
    "BHARATPE.90070079482@fbpe PARAS PHARMA CHEMIST DRUGIST GENERALS on 28-04-26. "
    "Your UPI transaction reference number is 463121241499."
)

def test_upi_debit_old_parses():
    assert email_parser.parse(UPI_DEBIT_OLD, RECEIVED) is not None

def test_upi_debit_old_amount():
    r = email_parser.parse(UPI_DEBIT_OLD, RECEIVED)
    assert r["amount"] == 70.00

def test_upi_debit_old_type_and_format():
    r = email_parser.parse(UPI_DEBIT_OLD, RECEIVED)
    assert r["type"] == "debit"
    assert r["format"] == "upi"

def test_upi_debit_old_account_last4():
    r = email_parser.parse(UPI_DEBIT_OLD, RECEIVED)
    assert r["account_last4"] == "1750"

def test_upi_debit_old_vpa_and_merchant():
    r = email_parser.parse(UPI_DEBIT_OLD, RECEIVED)
    assert r["vpa"] == "BHARATPE.90070079482@fbpe"
    assert r["merchant"] == "PARAS PHARMA CHEMIST DRUGIST GENERALS"

def test_upi_debit_old_upi_ref():
    r = email_parser.parse(UPI_DEBIT_OLD, RECEIVED)
    assert r["upi_ref"] == "463121241499"

def test_upi_debit_old_raw_entry():
    r = email_parser.parse(UPI_DEBIT_OLD, RECEIVED)
    assert r["raw_entry"] == "BHARATPE.90070079482@fbpe PARAS PHARMA CHEMIST DRUGIST GENERALS"

def test_upi_debit_old_card_last4_is_none():
    r = email_parser.parse(UPI_DEBIT_OLD, RECEIVED)
    assert r["card_last4"] is None

def test_upi_debit_old_date_is_utc():
    r = email_parser.parse(UPI_DEBIT_OLD, RECEIVED)
    assert r["date"].tzinfo == timezone.utc

# ---------------------------------------------------------------------------
# Format 1b: UPI Debit (new 2026 format)
# ---------------------------------------------------------------------------

UPI_DEBIT_NEW = (
    "Dear Customer, Greetings from HDFC Bank! Rs.12015.00 is debited from your account "
    "ending 1750 towards VPA MYNTRA@axl (Myntra) on 08-05-26. UPI transaction reference "
    "no.: 022327800326. If you did not authorise this, call 1800-202-6161."
)

def test_upi_debit_new_parses():
    assert email_parser.parse(UPI_DEBIT_NEW, RECEIVED) is not None

def test_upi_debit_new_amount():
    r = email_parser.parse(UPI_DEBIT_NEW, RECEIVED)
    assert r["amount"] == 12015.00

def test_upi_debit_new_type_and_format():
    r = email_parser.parse(UPI_DEBIT_NEW, RECEIVED)
    assert r["type"] == "debit"
    assert r["format"] == "upi"

def test_upi_debit_new_account_last4():
    r = email_parser.parse(UPI_DEBIT_NEW, RECEIVED)
    assert r["account_last4"] == "1750"

def test_upi_debit_new_vpa_and_merchant():
    r = email_parser.parse(UPI_DEBIT_NEW, RECEIVED)
    assert r["vpa"] == "MYNTRA@axl"
    assert r["merchant"] == "Myntra"

def test_upi_debit_new_upi_ref():
    r = email_parser.parse(UPI_DEBIT_NEW, RECEIVED)
    assert r["upi_ref"] == "022327800326"

def test_upi_debit_new_raw_entry():
    r = email_parser.parse(UPI_DEBIT_NEW, RECEIVED)
    assert r["raw_entry"] == "MYNTRA@axl Myntra"

def test_upi_debit_new_date_is_utc():
    r = email_parser.parse(UPI_DEBIT_NEW, RECEIVED)
    assert r["date"].tzinfo == timezone.utc

# ---------------------------------------------------------------------------
# Format 2: UPI Credit
# ---------------------------------------------------------------------------

UPI_CREDIT = (
    "Dear Customer, Rs. 7000.00 is successfully credited to your account **1750 by VPA "
    "ktkonceptz-1@okhdfcbank ZABIULLAKHAN H SO HAFIZULLAKHAN on 20-12-25. "
    "Your UPI transaction reference number is 115932677040."
)

def test_upi_credit_parses():
    assert email_parser.parse(UPI_CREDIT, RECEIVED) is not None

def test_upi_credit_amount():
    r = email_parser.parse(UPI_CREDIT, RECEIVED)
    assert r["amount"] == 7000.00

def test_upi_credit_type_and_format():
    r = email_parser.parse(UPI_CREDIT, RECEIVED)
    assert r["type"] == "credit"
    assert r["format"] == "upi"

def test_upi_credit_account_last4():
    r = email_parser.parse(UPI_CREDIT, RECEIVED)
    assert r["account_last4"] == "1750"

def test_upi_credit_vpa_and_merchant():
    r = email_parser.parse(UPI_CREDIT, RECEIVED)
    assert r["vpa"] == "ktkonceptz-1@okhdfcbank"
    assert r["merchant"] == "ZABIULLAKHAN H SO HAFIZULLAKHAN"

def test_upi_credit_upi_ref():
    r = email_parser.parse(UPI_CREDIT, RECEIVED)
    assert r["upi_ref"] == "115932677040"

def test_upi_credit_raw_entry():
    r = email_parser.parse(UPI_CREDIT, RECEIVED)
    assert r["raw_entry"] == "ktkonceptz-1@okhdfcbank ZABIULLAKHAN H SO HAFIZULLAKHAN"

def test_upi_credit_date_is_utc():
    r = email_parser.parse(UPI_CREDIT, RECEIVED)
    assert r["date"].tzinfo == timezone.utc

# ---------------------------------------------------------------------------
# Format 3: NetBanking
# ---------------------------------------------------------------------------

NETBANKING = (
    "Dear Customer, Thank you for using HDFC Bank NetBanking for payment of "
    "Rs. 900000.00 from A/c **********1750 to RAZPBSEINDIACOM"
)

def test_netbanking_parses():
    assert email_parser.parse(NETBANKING, RECEIVED) is not None

def test_netbanking_amount():
    r = email_parser.parse(NETBANKING, RECEIVED)
    assert r["amount"] == 900000.00

def test_netbanking_type_and_format():
    r = email_parser.parse(NETBANKING, RECEIVED)
    assert r["type"] == "debit"
    assert r["format"] == "netbanking"

def test_netbanking_account_last4():
    r = email_parser.parse(NETBANKING, RECEIVED)
    assert r["account_last4"] == "1750"

def test_netbanking_merchant():
    r = email_parser.parse(NETBANKING, RECEIVED)
    assert r["merchant"] == "RAZPBSEINDIACOM"
    assert r["raw_entry"] == "RAZPBSEINDIACOM"

def test_netbanking_date_is_received_at():
    r = email_parser.parse(NETBANKING, RECEIVED)
    assert r["date"] == RECEIVED

def test_netbanking_vpa_and_upi_ref_are_none():
    r = email_parser.parse(NETBANKING, RECEIVED)
    assert r["vpa"] is None
    assert r["upi_ref"] is None

# ---------------------------------------------------------------------------
# Format 4: Debit Card
# ---------------------------------------------------------------------------

DEBIT_CARD = (
    "Dear Customer,Greetings from HDFC Bank!"
    "Rs.299.00 is debited from your HDFC Bank Debit Card ending 4458 "
    "at YOUTUBEGOOGLE on 05 Apr, 2026 at 15:23:09."
)

def test_debit_card_parses():
    assert email_parser.parse(DEBIT_CARD, RECEIVED) is not None

def test_debit_card_amount():
    r = email_parser.parse(DEBIT_CARD, RECEIVED)
    assert r["amount"] == 299.00

def test_debit_card_type_and_format():
    r = email_parser.parse(DEBIT_CARD, RECEIVED)
    assert r["type"] == "debit"
    assert r["format"] == "debit_card"

def test_debit_card_card_last4():
    r = email_parser.parse(DEBIT_CARD, RECEIVED)
    assert r["card_last4"] == "4458"

def test_debit_card_merchant():
    r = email_parser.parse(DEBIT_CARD, RECEIVED)
    assert r["merchant"] == "YOUTUBEGOOGLE"
    assert r["raw_entry"] == "YOUTUBEGOOGLE"

def test_debit_card_account_last4_is_none():
    r = email_parser.parse(DEBIT_CARD, RECEIVED)
    assert r["account_last4"] is None

def test_debit_card_date_utc_value():
    r = email_parser.parse(DEBIT_CARD, RECEIVED)
    # 05 Apr 2026 15:23:09 IST = 05 Apr 2026 09:53:09 UTC
    assert r["date"] == datetime(2026, 4, 5, 9, 53, 9, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Unrecognised format
# ---------------------------------------------------------------------------

def test_unrecognised_returns_none():
    assert email_parser.parse("Some random email body.", RECEIVED) is None

def test_empty_body_returns_none():
    assert email_parser.parse("", RECEIVED) is None
