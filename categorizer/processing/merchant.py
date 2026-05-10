from __future__ import annotations


STOPWORDS = [
    "payment",
    "transfer",
    "upi",
    "neft",
    "rtgs",
    "imps",
    "ach",
    "pos",
    "dr",
    "dc",
    "txn",
    "intl",
    "billpay",
    "hdfc",
    "sbi",
    "icici",
    "axis",
    "kotak",
    "yes",
    "idfc",
    "pnb",
    "bob",
]


def extract_merchant(clean_text: str) -> str:
    """
    Extract a simple merchant key from cleaned transaction text.

    Steps:
    - split text into tokens
    - remove stopwords
    - return first meaningful token
    - fallback to 'unknown'
    """
    if clean_text is None:
        return "unknown"

    tokens = str(clean_text).split()

    for token in tokens:
        if len(token) <= 1:
            continue

        if token and token not in STOPWORDS:
            return token

    return "unknown"
