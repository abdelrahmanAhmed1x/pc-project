from __future__ import annotations

import json
import re
from urllib.parse import quote

from scrapling.spiders import Response

from pc_parts.models import CategorySeed
from pc_parts.normalization.categories import audio_type
from pc_parts.spiders.common import PartsSpider


def shopify_offers(item: dict, seed: CategorySeed, provider: str, base: str):
    handle, product_id = item.get("handle"), item.get("id")
    if not handle or not product_id:
        raise ValueError("Shopify product lacks handle or ID")
    title = item.get("title") or ""
    if re.search(r"\b(case|cover|protector|replacement tips|bundle)\b", title, re.I):
        return
    category = audio_type(title, seed.category) if seed.category in {
        "headphones", "headsets", "earphones", "true_wireless_earbuds"
    } else seed.category
    images = item.get("images") or []
    option_names = [o.get("name") for o in item.get("options") or []]
    for variant in item.get("variants") or []:
        options = {key: variant.get(f"option{index}") for index, key in enumerate(option_names, 1)
                   if key and variant.get(f"option{index}") not in (None, "Default Title")}
        image = variant.get("featured_image") or (images[0] if images else {})
        sku = (variant.get("sku") or "").strip() or None
        yield {
            "name": title, "category": category, "depth": seed.depth,
            "brand": item.get("vendor"), "provider": provider,
            "provider_product_id": str(product_id), "provider_variant_id": str(variant["id"]),
            "sku": sku, "manufacturer_part_number": sku if provider == "tradeline" and sku else None,
            "gtin": variant.get("barcode"),
            "variant": options, "price": variant.get("price"),
            "old_price": variant.get("compare_at_price"),
            "in_stock": variant.get("available"), "currency": "EGP",
            "product_url": f"{base}/products/{quote(handle)}",
            "image_url": image.get("src"),
            "specifications": {"description_html": item.get("body_html") or ""},
        }


class ShopifyTechSpider(PartsSpider):
    collections: dict[str, str] = {}
    page_size = 100

    async def parse(self, response: Response):
        try:
            self.check_response(response)
            body = response.body.decode("utf-8", "replace")
            currency = re.search(r'Shopify\.currency\s*=\s*\{[^}]*["\']active["\']\s*:\s*["\']([^"\']+)', body)
            if not currency or currency.group(1) != "EGP":
                raise ValueError("Shopify storefront currency is not EGP")
            seeds = [CategorySeed(f"{self.base_url}collections/{handle}", category, 1, handle)
                     for handle, category in self.collections.items()]
            if self.categories:
                seeds = [seed for seed in seeds if seed.category in self.categories]
            if self.limit_categories:
                seeds = seeds[:self.limit_categories]
            self.discovered = seeds
            for seed in seeds:
                yield response.follow(self.listing_url(seed, 1), callback=self.parse_listing,
                                      meta={"seed": seed, "page": 1})
        except Exception as exc:
            self.errors.append(f"Shopify discovery {response.url}: {exc}")
            yield None

    def listing_url(self, seed: CategorySeed, page: int) -> str:
        return f"{seed.url}/products.json?limit={self.page_size}&page={page}"

    async def parse_listing(self, response: Response):
        try:
            self.check_response(response)
            seed, page = response.meta["seed"], response.meta["page"]
            items = json.loads(response.body).get("products")
            if not isinstance(items, list):
                raise ValueError("Shopify collection lacks products list")
            if not items:
                self.finished_categories.add(seed.url)
                return
            self.check_page(seed.url, str(response.url), [str(item.get("id")) for item in items], page)
            for item in items:
                try:
                    for offer in shopify_offers(item, seed, self.name, self.base_url.rstrip("/")):
                        self.raw_count += 1
                        yield offer
                except (ValueError, TypeError, KeyError) as exc:
                    self.errors.append(f"Shopify product {item.get('id')}: {exc}")
            if len(items) == self.page_size and (self.limit_pages is None or page < self.limit_pages):
                yield response.follow(self.listing_url(seed, page + 1), callback=self.parse_listing,
                                      meta={"seed": seed, "page": page + 1})
            elif len(items) < self.page_size:
                self.finished_categories.add(seed.url)
        except Exception as exc:
            self.errors.append(f"Shopify collection {response.url}: {exc}")
            yield None


class Dream2000Spider(ShopifyTechSpider):
    name = "dream2000"
    base_url = "https://dream2000.com/"
    start_urls = ["https://dream2000.com/en"]
    allowed_domains = {"dream2000.com"}
    collections = {
        "mobiles": "mobile_phones", "laptop": "laptops",
        "airbuds": "true_wireless_earbuds", "headset": "headsets",
        "wired-headphone": "earphones", "ear-headphones": "headphones",
        "bluethooth-headphones": "headphones",
    }


class TradelineSpider(ShopifyTechSpider):
    name = "tradeline"
    base_url = "https://tradelinestores.com/"
    start_urls = [base_url]
    allowed_domains = {"tradelinestores.com"}
    collections = {
        "apl-ps-iphone-15": "mobile_phones", "apl-ps-iphone-16": "mobile_phones",
        "apl-ps-iphone-16e": "mobile_phones", "apl-ps-iphone-17": "mobile_phones",
        "apl-ps-iphone-17-pro": "mobile_phones", "apl-ps-iphone-17e": "mobile_phones",
        "apl-ps-iphone-18-pro": "mobile_phones", "apl-ps-iphone-air": "mobile_phones",
        "apl-ps-13-inch-macbook-air": "laptops", "apl-ps-15-inch-macbook-air": "laptops",
        "apl-ps-13-inch-macbook-neo": "laptops",
        "apl-ps-14-inch-macbook-pro-m5": "laptops",
        "apl-ps-14-inch-macbook-pro-m5-pro": "laptops",
        "apl-ps-14-inch-macbook-pro-m5-max": "laptops",
        "apl-ps-16-inch-macbook-pro-m5-pro": "laptops",
        "apl-ps-16-inch-macbook-pro-m5-max": "laptops",
        "airpods": "true_wireless_earbuds", "airpods-max": "headphones",
        "beats-music": "headphones",
    }
