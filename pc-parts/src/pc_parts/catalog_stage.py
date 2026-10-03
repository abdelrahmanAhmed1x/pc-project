from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from pathlib import Path

from pc_parts.normalization.products import InvalidProduct, clean_raw


def valid_gtin(value: str | None) -> bool:
    if not value or not re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", value):
        return False
    digits = [int(c) for c in value]
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(reversed(digits[:-1])))
    return (10 - total % 10) % 10 == digits[-1]


def identity_key(item: dict) -> str:
    variant = item.get("variant") or {}
    # Stable retailer identity is distinct from manufacturer matching evidence.
    # An MPN or GTIN can be wrong, reused by a seller, or reclassified later.
    source = item.get("provider_product_id") or item["product_url"]
    variant_id = item.get("provider_variant_id") or json.dumps(variant, sort_keys=True, ensure_ascii=False)
    return f"source:{item['provider']}:{source}:{variant_id}"


class CatalogStage:
    """Disk-backed, one-row-per-retailer-variant offer staging."""

    def __init__(self, provider: str, base_url: str):
        self.provider = provider
        self.base_url = base_url
        self._tmp = tempfile.TemporaryDirectory(prefix="catalog-stage-")
        self.db = sqlite3.connect(str(Path(self._tmp.name) / "offers.sqlite"))
        self.db.execute("CREATE TABLE records (source_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.invalid_count = 0
        self.invalid_examples: list[str] = []
        self.unknown_price_examples: list[str] = []

    def add(self, raw: dict):
        try:
            item = clean_raw(raw, self.provider, self.base_url)
            if item["condition"] not in {"new", "used", "refurbished", "unknown"}:
                raise InvalidProduct("invalid condition")
            if item.get("seller_id") and self.provider != "raya":
                raise InvalidProduct("unexpected marketplace seller")
            item["identity_key"] = identity_key(item)
            item["gtin"] = item.get("gtin") or (item.get("sku") if valid_gtin(item.get("sku")) else None)
            source = item.get("provider_product_id") or item["product_url"]
            variant = item.get("provider_variant_id") or json.dumps(item.get("variant") or {}, sort_keys=True)
            item["source_key"] = f"{source}:{variant}"
            if item["price_status"] != "known" and len(self.unknown_price_examples) < 5:
                self.unknown_price_examples.append(f"{item['product_url']} ({item['price_status']})")
            self.db.execute("INSERT OR REPLACE INTO records VALUES (?, ?)",
                            (item["source_key"], json.dumps(item, default=str, ensure_ascii=False)))
        except (InvalidProduct, ValueError, TypeError) as exc:
            self.invalid_count += 1
            if len(self.invalid_examples) < 20:
                self.invalid_examples.append(f"{raw.get('product_url')!r}: {exc}")

    def finish(self) -> int:
        self.db.commit()
        return self.db.execute("SELECT count(*) FROM records").fetchone()[0]

    def rows(self):
        for (payload,) in self.db.execute("SELECT payload FROM records ORDER BY source_key"):
            yield json.loads(payload)

    def close(self):
        self.db.close()
        self._tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
