"""
HDFC Bank transaction alert email parser.

Supports four email formats:
  - upi_debit    : UPI debit from account
  - upi_credit   : UPI credit to account
  - netbanking   : NetBanking payment
  - debit_card   : Debit card autopay
"""

import re
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# HDFC emails report times in IST (UTC+5:30).
IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_amount(s: str) -> float:
    """Strip commas (Indian number format) and return float."""
    return float(s.replace(",", ""))


def _parse_date_ddmmyy(s: str) -> datetime:
    """Parse DD-MM-YY (IST) and return UTC datetime."""
    dt = datetime.strptime(s, "%d-%m-%y").replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


def _parse_date_debit_card(date_s: str, time_s: str) -> datetime:
    """Parse 'DD Mon, YYYY' + 'HH:MM:SS' (IST) and return UTC datetime."""
    # Normalise any run of whitespace within the captured date group.
    date_s = " ".join(date_s.split())
    dt = datetime.strptime(f"{date_s} {time_s}", "%d %b, %Y %H:%M:%S").replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Format-detection predicates
# ---------------------------------------------------------------------------

def is_upi_debit(body: str) -> bool:
    return bool(re.search(r"has been debited from account", body, re.IGNORECASE))


def is_upi_credit(body: str) -> bool:
    return bool(re.search(r"is successfully credited to your account", body, re.IGNORECASE))


def is_netbanking(body: str) -> bool:
    return bool(re.search(r"HDFC Bank NetBanking for payment", body, re.IGNORECASE))


def is_debit_card(body: str) -> bool:
    return bool(re.search(
        r"is debited from your HDFC Bank Debit Card ending", body, re.IGNORECASE
    ))


# ---------------------------------------------------------------------------
# Per-format parsers
# ---------------------------------------------------------------------------

def parse_upi_debit(body: str, received_at: datetime) -> dict | None:
    """
    Sample:
      Rs.70.00 has been debited from account 1750 to VPA BHARATPE.90070079482@fbpe
      PARAS PHARMA CHEMIST DRUGIST GENERALS on 28-04-26.
      Your UPI transaction reference number is 463121241499.
    """
    m = re.search(
        r"Rs\.\s*([\d,]+\.\d{2})\s+has been debited from account\s+\**(\d+)"
        r"\s+to VPA\s+(\S+)\s+(.+?)\s+on\s+(\d{2}-\d{2}-\d{2})\."
        r"\s+Your UPI transaction reference number is\s+(\d+)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        logger.debug("parse_upi_debit: regex did not match")
        return None
    return {
        "amount": _parse_amount(m.group(1)),
        "type": "debit",
        "format": "upi",
        "account_last4": m.group(2)[-4:],
        "card_last4": None,
        "vpa": m.group(3),
        "merchant": m.group(4).strip(),
        "date": _parse_date_ddmmyy(m.group(5)),
        "upi_ref": m.group(6),
    }


def parse_upi_credit(body: str, received_at: datetime) -> dict | None:
    """
    Sample:
      Rs. 7000.00 is successfully credited to your account **1750 by VPA
      ktkonceptz-1@okhdfcbank ZABIULLAKHAN H SO HAFIZULLAKHAN on 20-12-25.
      Your UPI transaction reference number is 115932677040.
    """
    m = re.search(
        r"Rs\.\s*([\d,]+\.\d{2})\s+is successfully credited to your account\s+\**(\d+)"
        r"\s+by VPA\s+(\S+)\s+(.+?)\s+on\s+(\d{2}-\d{2}-\d{2})\."
        r"\s+Your UPI transaction reference number is\s+(\d+)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        logger.debug("parse_upi_credit: regex did not match")
        return None
    return {
        "amount": _parse_amount(m.group(1)),
        "type": "credit",
        "format": "upi",
        "account_last4": m.group(2)[-4:],
        "card_last4": None,
        "vpa": m.group(3),
        "merchant": m.group(4).strip(),
        "date": _parse_date_ddmmyy(m.group(5)),
        "upi_ref": m.group(6),
    }


def parse_netbanking(body: str, received_at: datetime) -> dict | None:
    """
    Sample:
      Thank you for using HDFC Bank NetBanking for payment of Rs. 900000.00
      from A/c **********1750 to RAZPBSEINDIACOM

    No date in email body — received_at is used as the transaction date.
    """
    m = re.search(
        r"HDFC Bank NetBanking for payment of Rs\.\s*([\d,]+\.\d{2})"
        r"\s+from A/c\s+\*+(\d+)\s+to\s+(\S+)",
        body,
        re.IGNORECASE,
    )
    if not m:
        logger.debug("parse_netbanking: regex did not match")
        return None
    return {
        "amount": _parse_amount(m.group(1)),
        "type": "debit",
        "format": "netbanking",
        "account_last4": m.group(2)[-4:],
        "card_last4": None,
        "vpa": None,
        "merchant": m.group(3).strip(),
        # No date in body — fall back to email receive time.
        "date": received_at.astimezone(timezone.utc),
        "upi_ref": None,
    }


def parse_debit_card(body: str, received_at: datetime) -> dict | None:
    """
    Sample:
      Rs.299.00 is debited from your HDFC Bank Debit Card ending 4458
      at YOUTUBEGOOGLE on 05 Apr, 2026 at 15:23:09.
    """
    m = re.search(
        r"Rs\.\s*([\d,]+\.\d{2})\s+is debited from your HDFC Bank Debit Card ending\s+(\d{4})"
        r"\s+at\s+(.+?)\s+on\s+(\d{2}\s+\w{3},\s+\d{4})\s+at\s+(\d{2}:\d{2}:\d{2})",
        body,
        re.IGNORECASE,
    )
    if not m:
        logger.debug("parse_debit_card: regex did not match")
        return None
    return {
        "amount": _parse_amount(m.group(1)),
        "type": "debit",
        "format": "debit_card",
        "account_last4": None,
        "card_last4": m.group(2),
        "vpa": None,
        "merchant": m.group(3).strip(),
        "date": _parse_date_debit_card(m.group(4), m.group(5)),
        "upi_ref": None,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse(body: str, received_at: datetime) -> dict | None:
    """
    Detect which HDFC format the email body belongs to and return a
    transaction dict with keys:
      amount, type, format, account_last4, card_last4, vpa, merchant, date, upi_ref

    Returns None if no format matches.
    """
    # Check most-specific patterns first to avoid ambiguous matches.
    if is_debit_card(body):
        return parse_debit_card(body, received_at)
    if is_netbanking(body):
        return parse_netbanking(body, received_at)
    if is_upi_debit(body):
        return parse_upi_debit(body, received_at)
    if is_upi_credit(body):
        return parse_upi_credit(body, received_at)
    logger.debug("parse: no format matched")
    return None


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _received = datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc)
    failures = 0

    def check(label: str, condition: bool, detail: str = "") -> None:
        global failures
        if condition:
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}" + (f"  —  {detail}" if detail else ""))
            failures += 1

    # -----------------------------------------------------------------------
    # Format 1: UPI Debit
    # -----------------------------------------------------------------------
    b1 = (
        "Dear Customer, Rs.70.00 has been debited from account 1750 to VPA "
        "BHARATPE.90070079482@fbpe PARAS PHARMA CHEMIST DRUGIST GENERALS on 28-04-26. "
        "Your UPI transaction reference number is 463121241499."
    )
    r1 = parse(b1, _received)
    check("F1 parse not None",       r1 is not None)
    check("F1 amount",               r1 and r1["amount"] == 70.00,     str(r1 and r1.get("amount")))
    check("F1 type",                 r1 and r1["type"] == "debit")
    check("F1 format",               r1 and r1["format"] == "upi")
    check("F1 account_last4",        r1 and r1["account_last4"] == "1750")
    check("F1 vpa",                  r1 and r1["vpa"] == "BHARATPE.90070079482@fbpe")
    check("F1 merchant",             r1 and r1["merchant"] == "PARAS PHARMA CHEMIST DRUGIST GENERALS")
    check("F1 upi_ref",              r1 and r1["upi_ref"] == "463121241499")
    check("F1 card_last4 is None",   r1 and r1["card_last4"] is None)
    check("F1 date is datetime",     r1 and isinstance(r1["date"], datetime))
    check("F1 date is UTC",          r1 and r1["date"].tzinfo == timezone.utc)
    print()

    # -----------------------------------------------------------------------
    # Format 2: UPI Credit
    # -----------------------------------------------------------------------
    b2 = (
        "Dear Customer, Rs. 7000.00 is successfully credited to your account **1750 by VPA "
        "ktkonceptz-1@okhdfcbank ZABIULLAKHAN H SO HAFIZULLAKHAN on 20-12-25. "
        "Your UPI transaction reference number is 115932677040."
    )
    r2 = parse(b2, _received)
    check("F2 parse not None",       r2 is not None)
    check("F2 amount",               r2 and r2["amount"] == 7000.00)
    check("F2 type",                 r2 and r2["type"] == "credit")
    check("F2 format",               r2 and r2["format"] == "upi")
    check("F2 account_last4",        r2 and r2["account_last4"] == "1750")
    check("F2 vpa",                  r2 and r2["vpa"] == "ktkonceptz-1@okhdfcbank")
    check("F2 merchant",             r2 and r2["merchant"] == "ZABIULLAKHAN H SO HAFIZULLAKHAN")
    check("F2 upi_ref",              r2 and r2["upi_ref"] == "115932677040")
    check("F2 date is UTC",          r2 and r2["date"].tzinfo == timezone.utc)
    print()

    # -----------------------------------------------------------------------
    # Format 3: NetBanking Debit
    # -----------------------------------------------------------------------
    b3 = (
        "Dear Customer, Thank you for using HDFC Bank NetBanking for payment of "
        "Rs. 900000.00 from A/c **********1750 to RAZPBSEINDIACOM"
    )
    r3 = parse(b3, _received)
    check("F3 parse not None",       r3 is not None)
    check("F3 amount",               r3 and r3["amount"] == 900000.00)
    check("F3 type",                 r3 and r3["type"] == "debit")
    check("F3 format",               r3 and r3["format"] == "netbanking")
    check("F3 account_last4",        r3 and r3["account_last4"] == "1750")
    check("F3 merchant",             r3 and r3["merchant"] == "RAZPBSEINDIACOM")
    check("F3 date == received_at",  r3 and r3["date"] == _received)
    check("F3 vpa is None",          r3 and r3["vpa"] is None)
    check("F3 upi_ref is None",      r3 and r3["upi_ref"] is None)
    print()

    # -----------------------------------------------------------------------
    # Format 4: Debit Card Autopay
    # -----------------------------------------------------------------------
    b4 = (
        "Dear Customer,Greetings from HDFC Bank!"
        "Rs.299.00 is debited from your HDFC Bank Debit Card ending 4458 "
        "at YOUTUBEGOOGLE on 05 Apr, 2026 at 15:23:09."
    )
    r4 = parse(b4, _received)
    check("F4 parse not None",       r4 is not None)
    check("F4 amount",               r4 and r4["amount"] == 299.00)
    check("F4 type",                 r4 and r4["type"] == "debit")
    check("F4 format",               r4 and r4["format"] == "debit_card")
    check("F4 card_last4",           r4 and r4["card_last4"] == "4458")
    check("F4 merchant",             r4 and r4["merchant"] == "YOUTUBEGOOGLE")
    check("F4 account_last4 None",   r4 and r4["account_last4"] is None)
    check("F4 date is UTC",          r4 and r4["date"].tzinfo == timezone.utc)
    # 05 Apr 2026 15:23:09 IST  =  05 Apr 2026 09:53:09 UTC
    expected_utc = datetime(2026, 4, 5, 9, 53, 9, tzinfo=timezone.utc)
    check("F4 date UTC value",       r4 and r4["date"] == expected_utc,
          str(r4 and r4.get("date")))
    print()

    # -----------------------------------------------------------------------
    # Unrecognised format
    # -----------------------------------------------------------------------
    r5 = parse("Some random email body.", _received)
    check("Unrecognised -> None",     r5 is None)
    print()

    if failures:
        print(f"{failures} test(s) FAILED.")
        sys.exit(1)
    else:
        print("All tests passed.")
