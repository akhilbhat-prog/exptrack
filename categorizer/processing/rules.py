from __future__ import annotations

import json
from pathlib import Path

from processing.cleaner import clean_entry


def load_rules(path: str) -> dict:
    """Load rule mappings from a JSON file."""
    rules_path = Path(path)

    with rules_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def apply_rules(text: str, rules: dict, amount: float | None = None):
    """
    Return the first matching rule for the provided text.

    Matching is based on cleaned keyword containment, with longer keywords
    checked first so more specific rules win over generic ones.
    """
    if text is None:
        return None

    normalized_text = clean_entry(text)
    normalized_rules = sorted(
        rules.items(),
        key=lambda item: len(clean_entry(item[0])),
        reverse=True,
    )

    for keyword, mapping in normalized_rules:
        normalized_keyword = clean_entry(keyword)
        if normalized_keyword and normalized_keyword in normalized_text:
            matched_rule = {
                "category": mapping.get("category", "Unknown"),
                "subcategory": mapping.get("subcategory", "Unknown"),
                "type": str(mapping.get("type", "Unknown")).title(),
                "confidence": float(mapping.get("confidence", 0.0)),
                "matched_keyword": keyword,
            }
            return _apply_amount_overrides(matched_rule, normalized_keyword, amount)

    return None


def _apply_amount_overrides(
    matched_rule: dict, normalized_keyword: str, amount: float | None
) -> dict:
    """
    Adjust matched rules when transaction-specific conditions apply.
    """
    if normalized_keyword == "uber" and amount is not None and amount > 150:
        updated_rule = matched_rule.copy()
        updated_rule["subcategory"] = "Cab"
        return updated_rule

    return matched_rule
