from __future__ import annotations

import json
import re

from scrapling.spiders import Response

from pc_parts.models import CategorySeed
from pc_parts.spiders.common import PartsSpider
from pc_parts.normalization.categories import audio_type


API = "https://api.switchpluseg.com"


def relevant_accessory(name: str) -> bool:
    return bool(re.search(r"airpods|earpods|earbuds?|earphones?|headphones?|headset|beats", name, re.I)) and not bool(
        re.search(r"\b(case|cover|adapter|protector|cable|replacement|charger)\b", name, re.I)
    )


class SwitchPlusSpider(PartsSpider):
    name = "switchplus"
    base_url = "https://switchpluseg.com/"
    start_urls = [f"{API}/api/customer/home/categories"]
    allowed_domains = {"api.switchpluseg.com", "switchpluseg.com"}
    concurrent_requests = 2
    concurrent_requests_per_domain = 2

    async def parse(self, response: Response):
        try:
            self.check_response(response)
            roots = json.loads(response.body).get("data") or []
            approved = {1: "laptops", 2: "mobile_phones", 6: "true_wireless_earbuds", 7: "headphones"}
            seeds = [CategorySeed(f"{API}/api/customer/categories/{root['id']}", approved[root["id"]], 1, root["name"])
                     for root in roots if root.get("id") in approved]
            if set(approved) != {int(seed.url.rsplit("/", 1)[-1]) for seed in seeds}:
                raise ValueError("Switch Plus category hierarchy changed")
            if self.categories:
                seeds = [seed for seed in seeds if seed.category in self.categories]
            if self.limit_categories:
                seeds = seeds[:self.limit_categories]
            self.discovered = seeds
            for seed in seeds:
                yield response.follow(f"{seed.url}?page=1", callback=self.parse_listing,
                                      meta={"seed": seed, "page": 1})
        except Exception as exc:
            self.errors.append(f"Switch Plus discovery: {exc}")
            yield None

    async def parse_listing(self, response: Response):
        try:
            self.check_response(response)
            seed, page = response.meta["seed"], response.meta["page"]
            payload = json.loads(response.body)
            data = payload.get("data") or {}
            items, total = data.get("items"), data.get("total")
            if payload.get("code") != 200 or not isinstance(items, list) or not isinstance(total, int):
                raise ValueError("invalid Switch Plus category response")
            if not items and total == 0:
                self.finished_categories.add(seed.url)
                return
            self.check_page(seed.url, str(response.url), [str(item.get("id")) for item in items], page)
            for item in items:
                if seed.category == "laptops" and not re.search(r"\bmacbook\b", item.get("name") or "", re.I):
                    continue
                if seed.category == "mobile_phones" and not re.search(r"\biphone\b", item.get("name") or "", re.I):
                    continue
                if seed.label == "Accessories" and not relevant_accessory(item.get("name") or ""):
                    continue
                yield response.follow(f"{API}/api/customer/products/{item['id']}", callback=self.parse_detail,
                                      meta={"seed": seed, "product_id": item["id"]})
            if page * 20 < total and (self.limit_pages is None or page < self.limit_pages):
                yield response.follow(f"{seed.url}?page={page + 1}", callback=self.parse_listing,
                                      meta={"seed": seed, "page": page + 1})
            elif page * 20 >= total:
                self.finished_categories.add(seed.url)
        except Exception as exc:
            self.errors.append(f"Switch Plus listing {response.url}: {exc}")
            yield None

    async def parse_detail(self, response: Response):
        try:
            self.check_response(response)
            payload = json.loads(response.body)
            product = (payload.get("data") or {}).get("product") or {}
            if payload.get("code") != 200 or product.get("id") != response.meta["product_id"]:
                raise ValueError("Switch Plus detail ID mismatch")
            seed = response.meta["seed"]
            category = seed.category
            if seed.label == "Accessories":
                category = audio_type(product.get("name") or "", "headphones")
            elif seed.label == "AirPods":
                category = audio_type(product.get("name") or "", "true_wireless_earbuds")
            brand = ((product.get("details") or {}).get("brand") or {}).get("name")
            for variant in product.get("product_variants") or []:
                options = {option["option"]["name"]: option["values"][0]["name"]
                           for option in variant.get("options") or []
                           if option.get("option") and option.get("values")}
                sku = variant.get("sku")
                offer = {
                    "provider": self.name, "provider_product_id": str(product["id"]),
                    "provider_variant_id": str(variant["id"]), "name": product.get("name"),
                    "category": category, "depth": seed.depth, "brand": brand,
                    "sku": sku, "manufacturer_part_number": sku if brand == "Apple" else None,
                    "variant": options, "price": variant.get("discount_price") or variant.get("price"),
                    "old_price": variant.get("price") if variant.get("discount_price") else None,
                    "in_stock": variant.get("in_stock"), "currency": "EGP",
                    "product_url": f"https://switchpluseg.com/item/{product['id']}",
                    "image_url": variant.get("image") or product.get("image"),
                    "specifications": {"attributes": (product.get("details") or {}).get("attributes") or []},
                }
                self.raw_count += 1
                yield offer
        except Exception as exc:
            self.errors.append(f"Switch Plus detail {response.url}: {exc}")
            yield None
