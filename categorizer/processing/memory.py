from __future__ import annotations

from collections import Counter, defaultdict

MIN_ROWS = 2
MIN_SHARE = 0.8


def memory_key(vpa, db_merchant) -> str:
    """
    Identify the payee: the UPI ID when there is one (unique per payee), else the
    parser's merchant name. Empty when neither is known.
    """
    vpa = (vpa or "").strip().lower()
    if vpa:
        return f"vpa:{vpa}"
    merchant = " ".join((db_merchant or "").split()).upper()
    return f"merchant:{merchant}" if merchant else ""


class MerchantMemory:
    """
    Store merchant-level corrections or known classifications for reuse.
    """

    def __init__(self):
        self.memory: dict[str, dict] = {}

    def lookup(self, merchant: str):
        if not merchant:
            return None

        return self.memory.get(merchant)

    def update(self, merchant: str, category: str, subcategory: str, type_: str):
        if not merchant:
            return

        self.memory[merchant] = {
            "category": category,
            "subcategory": subcategory,
            "type": type_,
            "confidence": 0.95,
        }

    @classmethod
    def from_history(cls, history_df, min_rows: int = MIN_ROWS, min_share: float = MIN_SHARE):
        """
        Build memory from labelled history (parse_database() columns). A payee is
        remembered only when it has at least `min_rows` rows and one
        (category, subcategory, type) covers at least `min_share` of them.
        """
        labels: dict[str, Counter] = defaultdict(Counter)
        for row in history_df.itertuples(index=False):
            key = memory_key(row.vpa, row.db_merchant)
            if not key or not row.final_category:
                continue
            labels[key][(row.final_category, row.final_subcategory, row.final_type)] += 1

        memory = cls()
        for key, counts in labels.items():
            total = sum(counts.values())
            (category, subcategory, type_), top = counts.most_common(1)[0]
            if total >= min_rows and top / total >= min_share:
                memory.memory[key] = {
                    "category": category,
                    "subcategory": subcategory,
                    "type": type_,
                    "confidence": round(top / total, 4),
                }
        return memory
