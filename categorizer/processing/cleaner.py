from __future__ import annotations

import re


_NON_ALPHA_PATTERN = re.compile(r"[^a-z\s]")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_HANDLE_WITH_DIGITS = re.compile(r"\d")


def clean_entry(text: str) -> str:
    """
    Normalize a transaction description for downstream merchant extraction and
    classification.

    Steps:
    - lowercase
    - remove numbers
    - remove special characters
    - normalize whitespace
    """
    if text is None:
        return ""

    cleaned = str(text).lower()
    cleaned = _NON_ALPHA_PATTERN.sub(" ", cleaned)
    cleaned = _WHITESPACE_PATTERN.sub(" ", cleaned).strip()

    return cleaned


def extract_vpa_handle(vpa: str) -> str:
    """
    Extract the merchant-identifying handle from a UPI VPA (e.g. 'swiggy.bng' from
    'swiggy.bng@icici'). Returns empty string for phone-number handles (P2P transfers)
    and missing/malformed VPAs.
    """
    if not vpa or "@" not in vpa:
        return ""

    handle = vpa.split("@")[0].strip()

    if not handle or _HANDLE_WITH_DIGITS.search(handle):
        return ""

    handle = handle.replace(".", " ").replace("-", " ").replace("_", " ").lower()
    handle = _NON_ALPHA_PATTERN.sub(" ", handle)
    return _WHITESPACE_PATTERN.sub(" ", handle).strip()
