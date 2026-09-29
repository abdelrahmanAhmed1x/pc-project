from __future__ import annotations

import html
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from scrapling.spiders import Response

from pc_parts.models import CategorySeed
from pc_parts.normalization.categories import CANONICAL_CATEGORIES
from pc_parts.spiders.common import PartsSpider


ALFRENSIA_CATEGORIES = {
    "processor": "cpu", "graphics-card": "gpu", "motherboard": "motherboard",
    "ram": "ram", "ssd": "ssd", "hdd": "hdd", "cases": "case",
    "power-supply": "power_supply", "air-liquid-cooling": "cooling",
    "case-fans": "cooling",
}
PAGE_SIZE = 100


def alfrensia_last_page(headers) -> int:
    for key, value in headers.items():
        if str(key).lower() == "x-wp-totalpages":
            last = int(value)
            if last < 1:
                raise ValueError("invalid product page count")
            return last
    raise ValueError("product API omitted X-WP-TotalPages")


def alfrensia_seeds(categories: list[dict]) -> list[CategorySeed]:
    seeds = []
    for item in categories:
        slug = item.get("slug")
        category = ALFRENSIA_CATEGORIES.get(slug)
        if not category:
            continue
        category_id = item.get("id")
        if not isinstance(category_id, int) or category_id <= 0:
            raise ValueError(f"invalid category ID for {slug}")
        url = "https://alfrensia.com/wp-json/wc/store/v1/products?" + urlencode(
            {"category": category_id, "per_page": PAGE_SIZE, "page": 1}
        )
        seeds.append(CategorySeed(url, category, 1, html.unescape(item.get("name") or slug)))
    missing = set(CANONICAL_CATEGORIES) - {seed.category for seed in seeds}
    if missing:
        raise ValueError(f"Alfrensia approved categories missing: {sorted(missing)}")
    return sorted(seeds, key=lambda seed: (seed.category, seed.label, seed.url))


def alfrensia_product(item: dict, seed: CategorySeed) -> dict:
    prices = item.get("prices") or {}
    currency = prices.get("currency_code")
    if currency != "EGP":
        raise ValueError(f"unexpected currency {currency!r}")
    minor = prices.get("currency_minor_unit")
    if not isinstance(minor, int) or not 0 <= minor <= 3:
        raise ValueError(f"invalid currency minor unit {minor!r}")
    amount = None
    if prices.get("price") not in (None, ""):
        try:
            amount = Decimal(str(prices["price"])) / (10 ** minor)
        except InvalidOperation as exc:
            raise ValueError("malformed price") from exc
    brands = item.get("brands") or []
    images = item.get("images") or []
    return {
        "name": html.unescape(item.get("name") or ""),
        "product_url": item.get("permalink"),
        "category": seed.category, "depth": seed.depth,
        "brand": html.unescape(brands[0].get("name") or "") if brands else None,
        "price": amount, "in_stock": item.get("is_in_stock"),
        "image_url": images[0].get("src") if images else None,
        "provider": "alfrensia", "currency": currency,
    }


class AlfrensiaSpider(PartsSpider):
    name = "alfrensia"
    base_url = "https://alfrensia.com/en/"
    start_urls = ["https://alfrensia.com/wp-json/wc/store/v1/products/categories?per_page=100&page=1"]
    allowed_domains = {"alfrensia.com"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.category_records: list[dict] = []

    async def parse(self, response: Response):
        try:
            self.check_response(response)
            categories = json.loads(response.body)
            if not isinstance(categories, list):
                raise ValueError("category API did not return a list")
            self.category_records.extend(categories)
            page = response.meta.get("page", 1)
            if len(categories) == PAGE_SIZE:
                url = f"https://alfrensia.com/wp-json/wc/store/v1/products/categories?per_page={PAGE_SIZE}&page={page + 1}"
                yield response.follow(url, callback=self.parse, meta={"page": page + 1})
                return
            seeds = alfrensia_seeds(self.category_records)
            if self.categories:
                seeds = [seed for seed in seeds if seed.category in self.categories]
            if self.limit_categories:
                seeds = seeds[:self.limit_categories]
            self.discovered = seeds
            for seed in seeds:
                yield response.follow(seed.url, callback=self.parse_listing, meta={"seed": seed, "page": 1})
        except Exception as exc:
            self.errors.append(f"Alfrensia category API {response.url}: {exc}")
            yield None

    async def parse_listing(self, response: Response):
        try:
            self.check_response(response)
            seed = response.meta["seed"]
            page = response.meta["page"]
            items = json.loads(response.body)
            if not isinstance(items, list):
                raise ValueError("product API did not return a list")
            last = alfrensia_last_page(response.headers)
            if page > last:
                raise ValueError(f"product page {page} exceeds reported last page {last}")
            urls = [item.get("permalink") or f"missing:{page}:{index}" if isinstance(item, dict)
                    else f"invalid:{page}:{index}" for index, item in enumerate(items)]
            self.check_page(seed.url, str(response.url), urls, page)
            self.check_last_page(seed.url, last)
            for item in items:
                try:
                    product = alfrensia_product(item, seed)
                except (ValueError, TypeError, AttributeError, IndexError) as exc:
                    self.logger.warning("alfrensia category=%s page=%s product=%s: %s",
                                        seed.label, page, item.get("id") if isinstance(item, dict) else None, exc)
                    continue
                self.raw_count += 1
                yield product
            if page < last and (self.limit_pages is None or page < self.limit_pages):
                url = seed.url.rsplit("page=", 1)[0] + f"page={page + 1}"
                yield response.follow(url, callback=self.parse_listing, meta={"seed": seed, "page": page + 1})
            elif page == last:
                self.finished_categories.add(seed.url)
        except Exception as exc:
            self.errors.append(f"Alfrensia listing {response.url}: {exc}")
            yield None
