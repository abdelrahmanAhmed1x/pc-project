from __future__ import annotations

import html
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from scrapling.spiders import Response

from pc_parts.models import CategorySeed
from pc_parts.normalization.categories import CANONICAL_CATEGORIES
from pc_parts.spiders.common import PartsSpider, soup_of


COMPUMARTS_COLLECTIONS = {
    "pc-parts-proccesor": "cpu", "pc-parts-graphic-card": "gpu",
    "pc-parts-mother-board": "motherboard", "pc-parts-ram-1": "ram",
    "storage-ssd": "ssd", "storage-hdd": "hdd",
    "pc-parts-computer-cases": "case", "pc-parts-power-supply": "power_supply",
    "pc-parts-cooling-solutions": "cooling", "computer-fan": "cooling",
}
PAGE_SIZE = 100


def compumarts_seeds(body: bytes | str) -> list[CategorySeed]:
    soup = soup_of(body)
    found = {}
    for anchor in soup.select("a[href]"):
        url = urljoin("https://www.compumarts.com", anchor["href"])
        parts = urlsplit(url)
        if parts.hostname not in {"www.compumarts.com", "compumarts.com"}:
            continue
        slug = parts.path.rstrip("/").split("/")[-1]
        category = COMPUMARTS_COLLECTIONS.get(slug)
        if category:
            found[slug] = CategorySeed(f"https://www.compumarts.com/collections/{slug}",
                                       category, 1, anchor.get_text(" ", strip=True) or slug)
    missing = set(CANONICAL_CATEGORIES) - {seed.category for seed in found.values()}
    if missing:
        raise ValueError(f"Compumarts approved collections missing: {sorted(missing)}")
    return sorted(found.values(), key=lambda seed: (seed.category, seed.label, seed.url))


def compumarts_product(item: dict, seed: CategorySeed) -> dict:
    title = item.get("title") or ""
    product_type = item.get("product_type") or ""
    if re.search(r"\bbundles?\b|\bpre[- ]?built\b", f"{title} {product_type}", re.I):
        raise ValueError("bundle or prebuilt product outside component scope")
    variants = item.get("variants") or []
    if not isinstance(variants, list):
        raise ValueError("invalid variants")
    available = [variant for variant in variants if variant.get("available") is True]
    stock = (True if available else False if variants and
             all(variant.get("available") is False for variant in variants) else None)
    priced = available or variants
    prices = []
    for variant in priced:
        if variant.get("price") in (None, ""):
            continue
        try:
            prices.append(Decimal(str(variant["price"])))
        except InvalidOperation:
            continue
    price = min(prices) if prices else None
    images = item.get("images") or []
    handle = item.get("handle")
    if not isinstance(handle, str) or not handle:
        raise ValueError("missing product handle")
    return {
        "name": html.unescape(title),
        "product_url": f"https://www.compumarts.com/products/{handle}",
        "category": seed.category, "depth": seed.depth,
        "brand": html.unescape(item.get("vendor") or ""),
        "price": price, "in_stock": stock,
        "image_url": images[0].get("src") if images else None,
        "provider": "compumarts", "currency": "EGP",
    }


class CompumartsSpider(PartsSpider):
    name = "compumarts"
    base_url = "https://www.compumarts.com/"
    start_urls = ["https://www.compumarts.com/collections"]
    allowed_domains = {"compumarts.com"}

    async def parse(self, response: Response):
        try:
            self.check_response(response)
            text = response.body.decode("utf-8", "replace")
            currency = re.search(r'Shopify\.currency\s*=\s*\{[^}]*["\']active["\']\s*:\s*["\']([^"\']+)', text)
            if not currency or currency.group(1) != "EGP":
                raise ValueError("storefront currency could not be verified as EGP")
            seeds = compumarts_seeds(response.body)
            if self.categories:
                seeds = [seed for seed in seeds if seed.category in self.categories]
            if self.limit_categories:
                seeds = seeds[:self.limit_categories]
            self.discovered = seeds
            for seed in seeds:
                yield response.follow(self.listing_url(seed, 1), callback=self.parse_listing,
                                      meta={"seed": seed, "page": 1})
        except Exception as exc:
            self.errors.append(f"Compumarts discovery {response.url}: {exc}")
            yield None

    @staticmethod
    def listing_url(seed: CategorySeed, page: int) -> str:
        return f"{seed.url}/products.json?limit={PAGE_SIZE}&page={page}"

    async def parse_listing(self, response: Response):
        try:
            self.check_response(response)
            seed = response.meta["seed"]
            page = response.meta["page"]
            payload = json.loads(response.body)
            items = payload.get("products")
            if not isinstance(items, list):
                raise ValueError("collection JSON did not contain products")
            if not items and page > 1:
                self.finished_categories.add(seed.url)
                return
            ids = [str(item.get("id") or f"missing:{page}:{index}") if isinstance(item, dict)
                   else f"invalid:{page}:{index}" for index, item in enumerate(items)]
            self.check_page(seed.url, str(response.url), ids, page)
            for item in items:
                try:
                    product = compumarts_product(item, seed)
                except (ValueError, TypeError, AttributeError, IndexError) as exc:
                    self.logger.warning("compumarts collection=%s page=%s product=%s: %s",
                                        seed.label, page, item.get("id") if isinstance(item, dict) else None, exc)
                    continue
                self.raw_count += 1
                yield product
            if len(items) == PAGE_SIZE and (self.limit_pages is None or page < self.limit_pages):
                yield response.follow(self.listing_url(seed, page + 1), callback=self.parse_listing,
                                      meta={"seed": seed, "page": page + 1})
            elif len(items) < PAGE_SIZE:
                self.finished_categories.add(seed.url)
        except Exception as exc:
            self.errors.append(f"Compumarts listing {response.url}: {exc}")
            yield None
