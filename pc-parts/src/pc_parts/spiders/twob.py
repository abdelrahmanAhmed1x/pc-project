from __future__ import annotations

import re
from urllib.parse import urljoin

from scrapling.spiders import Response

from pc_parts.models import CategorySeed
from pc_parts.spiders.common import PartsSpider, jsonld_fields, product_jsonld, soup_of


class TwoBSpider(PartsSpider):
    name = "twob"
    base_url = "https://2b.com.eg/en/"
    start_urls = [base_url]
    allowed_domains = {"2b.com.eg"}
    paths = {
        "mobile-and-tablet/mobiles.html": "mobile_phones",
        "computers/laptops.html": "laptops",
        "audio/headphones/headphones.html": "headphones",
        "audio/headphones/in-ear-headphone.html": "earphones",
        "audio/headphones/true-wireless-headphones.html": "true_wireless_earbuds",
        "gaming/gaming-acc/gaming-headphones.html": "headsets",
    }

    async def parse(self, response: Response):
        try:
            self.check_response(response)
            soup = soup_of(response)
            links = {a.get("href") for a in soup.select("a[href]")}
            seeds = [CategorySeed(urljoin(self.base_url, path), category, 1, path)
                     for path, category in self.paths.items()
                     if urljoin(self.base_url, path) in links]
            if len(seeds) != len(self.paths):
                raise ValueError("2B approved category links missing")
            if self.categories:
                seeds = [seed for seed in seeds if seed.category in self.categories]
            if self.limit_categories:
                seeds = seeds[:self.limit_categories]
            self.discovered = seeds
            for seed in seeds:
                yield response.follow(seed.url, callback=self.parse_listing,
                                      meta={"seed": seed, "page": 1})
        except Exception as exc:
            self.errors.append(f"2B discovery: {exc}")
            yield None

    async def parse_listing(self, response: Response):
        try:
            self.check_response(response)
            seed, page = response.meta["seed"], response.meta["page"]
            soup = soup_of(response)
            cards = soup.select("ol.products.list.items.product-items > li.product-item")
            urls = [a["href"] for card in cards if (a := card.select_one("a.product-item-link[href]"))]
            self.check_page(seed.url, str(response.url), urls, page)
            for url in urls:
                yield response.follow(url, callback=self.parse_detail, meta={"seed": seed})
            next_link = soup.select_one("a.action.next[href]")
            if next_link and (self.limit_pages is None or page < self.limit_pages):
                yield response.follow(next_link["href"], callback=self.parse_listing,
                                      meta={"seed": seed, "page": page + 1})
            elif not next_link:
                self.finished_categories.add(seed.url)
        except Exception as exc:
            self.errors.append(f"2B listing {response.url}: {exc}")
            yield None

    async def parse_detail(self, response: Response):
        try:
            self.check_response(response)
            soup, seed = soup_of(response), response.meta["seed"]
            ld = product_jsonld(soup, str(response.url), self.name)
            fields = jsonld_fields(ld)
            if not ld or not fields:
                raise ValueError("2B Product JSON-LD missing")
            offers = ld.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            seller = offers.get("seller") or {}
            if isinstance(seller, dict) and seller.get("name") not in (None, "2B"):
                raise ValueError("2B product has unexpected seller")
            specs = {}
            for row in soup.select("#product-attribute-specs-table tr"):
                key, value = row.select_one("th"), row.select_one("td")
                if key and value:
                    specs[key.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
            sku_el = soup.select_one(".product-sku .spec-value")
            warranty = specs.get("warranty") or specs.get("Warranty")
            if not warranty:
                heading = soup.find(string=re.compile(r"^Warranty$", re.I))
                warranty = heading.find_next("p").get_text(" ", strip=True) if heading and heading.find_next("p") else None
            old = soup.select_one(".product-info-main .old-price [data-price-amount]")
            mpn = ld.get("mpn") or specs.get("MPN")
            model = specs.get("Model Number")
            gtin = next((ld.get(key) for key in ("gtin14", "gtin13", "gtin12", "gtin8", "gtin")
                         if ld.get(key)), None)
            image = fields.get("image_url")
            if isinstance(image, dict):
                image = image.get("url")
            self.raw_count += 1
            yield {
                "provider": self.name,
                "provider_product_id": str(ld.get("productID") or (sku_el.get_text(strip=True) if sku_el else ld.get("sku") or "")),
                "name": ld.get("name") or (soup.select_one("h1").get_text(" ", strip=True) if soup.select_one("h1") else ""),
                "category": seed.category, "depth": seed.depth,
                "brand": fields.get("brand") or specs.get("Brand"),
                "sku": sku_el.get_text(strip=True) if sku_el else ld.get("sku"),
                "manufacturer_part_number": mpn, "model_number": model,
                "gtin": gtin, "price": fields.get("price"),
                "old_price": old.get("data-price-amount") if old else None,
                "in_stock": fields.get("in_stock"), "currency": "EGP",
                "product_url": str(response.url), "image_url": image,
                "warranty": warranty, "specifications": specs,
            }
        except Exception as exc:
            self.errors.append(f"2B detail {response.url}: {exc}")
            yield None
