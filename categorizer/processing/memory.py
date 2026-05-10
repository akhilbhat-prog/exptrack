from __future__ import annotations


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
