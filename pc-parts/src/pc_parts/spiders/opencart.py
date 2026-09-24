from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from scrapling.spiders import Response

from pc_parts.spiders.common import (
    PartsSpider, discover_opencart, jsonld_fields, opencart_cards,
    opencart_explicitly_empty, opencart_page, product_jsonld, soup_of,
)
from pc_parts.normalization.products import parse_stock
from pc_parts.normalization.products import canonical_url


class OpenCartSpider(PartsSpider):
    detail_for_all = False

    async def parse(self, response: Response):
        try:
            self.check_response(response)
            seeds = discover_opencart(response.body, self.name, self.base_url)
            if self.categories:
                seeds = [seed for seed in seeds if seed.category in self.categories]
            if self.limit_categories:
                seeds = seeds[: self.limit_categories]
            self.discovered = seeds
            for seed in seeds:
                yield response.follow(seed.url, callback=self.parse_listing, meta={"seed": seed, "page": 1})
        except Exception as exc:
            self.errors.append(f"category discovery: {exc}")
            yield None

    async def parse_listing(self, response: Response):
        try:
            self.check_response(response)
            seed = response.meta["seed"]
            page = response.meta["page"]
            soup = soup_of(response)
            cards = opencart_cards(soup, seed.category, seed.depth, self.base_url, self.name)
            if not cards and page == 1 and not soup.select_one("ul.pagination") and opencart_explicitly_empty(soup):
                self.visited_pages.add(str(response.url))
                self.finished_categories.add(seed.url)
                self.logger.info("Confirmed empty category: %s", seed.url)
                return
            self.check_page(seed.url, str(response.url), [c.get("product_url", "") for c in cards], page)
            next_href, last = opencart_page(soup, page)
            self.check_last_page(seed.url, last)
            if not soup.select_one("ul.pagination") and len(cards) >= 12:
                raise RuntimeError("full listing page has no pagination evidence")
            for card in cards:
                if self.detail_for_all or card["in_stock"] is None:
                    if card.get("product_url"):
                        yield response.follow(card["product_url"], callback=self.parse_detail,
                                              meta={"product": card}, dont_filter=True)
                    else:
                        self.raw_count += 1
                        yield card
                else:
                    self.raw_count += 1
                    yield card
            if next_href and (self.limit_pages is None or page < self.limit_pages):
                yield response.follow(urljoin(str(response.url), next_href), callback=self.parse_listing,
                                      meta={"seed": seed, "page": page + 1})
            elif not next_href:
                self.finished_categories.add(seed.url)
        except Exception as exc:
            self.errors.append(f"listing {response.url}: {exc}")
            yield None

    async def parse_detail(self, response: Response):
        try:
            self.check_response(response)
            card = dict(response.meta["product"])
            soup = soup_of(response)
            canonical = soup.select_one('link[rel="canonical"][href]')
            if canonical:
                source = canonical_url(card["product_url"], self.base_url, self.name)
                chosen = canonical_url(canonical["href"], self.base_url, self.name)
                if not urlsplit(source).path.endswith("/index.php") and source.rsplit("/", 1)[-1] != chosen.rsplit("/", 1)[-1]:
                    raise RuntimeError("canonical product URL points to a different slug")
                card["product_url"] = chosen
            detail_stock = soup.select_one(".product-stock")
            ld = jsonld_fields(product_jsonld(soup, str(response.url), self.name))
            if detail_stock:
                card["in_stock"] = parse_stock(detail_stock.get_text(" ", strip=True))
            if card["in_stock"] is None:
                card["in_stock"] = ld.get("in_stock")
            if not card.get("brand"):
                card["brand"] = ld.get("brand")
            if not card.get("price"):
                card["price"] = ld.get("price")
            if not card.get("image_url"):
                card["image_url"] = ld.get("image_url")
            self.raw_count += 1
            yield card
        except Exception as exc:
            self.errors.append(f"detail {response.url}: {exc}")
            yield None
