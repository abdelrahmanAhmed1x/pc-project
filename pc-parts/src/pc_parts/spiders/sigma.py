from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from scrapling.spiders import Response

from pc_parts.models import CategorySeed
from pc_parts.normalization.categories import CANONICAL_CATEGORIES, sigma_category
from pc_parts.normalization.products import parse_price
from pc_parts.spiders.common import PartsSpider, jsonld_fields, product_jsonld, soup_of


def discover_sigma(html: str | bytes) -> list[CategorySeed]:
    soup = soup_of(html)
    flight = []
    for script in soup.select("script"):
        for match in re.finditer(r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)', script.string or ""):
            flight.append(json.loads(match.group(1)))
    text = "".join(flight)
    key = '"initialCategories":'
    position = text.find(key)
    if position < 0:
        raise RuntimeError("Sigma category hierarchy missing from server response")
    categories, _ = json.JSONDecoder().raw_decode(text[position + len(key):])
    seeds = []

    def walk(node: dict, parents: tuple[str, ...]):
        path = (*parents, node["name"])
        category = sigma_category(path)
        if category:
            seeds.append(CategorySeed(f"https://www.sigma-computer.com/en/category/{node['id']}", category,
                                      len(path), " / ".join(path)))
        for child in node.get("subcategories") or []:
            walk(child, path)

    for root in categories:
        walk(root, ())
    missing = set(CANONICAL_CATEGORIES) - {seed.category for seed in seeds}
    if missing:
        raise RuntimeError(f"Sigma approved categories missing: {sorted(missing)}")
    return sorted(seeds, key=lambda s: (s.category, s.label, s.url))


def sigma_page(soup, page: int, card_count: int = 0) -> tuple[int, bool]:
    nav = soup.select_one('nav[aria-label="pagination"]')
    if not nav:
        if page > 1 or card_count >= 16:
            raise RuntimeError(f"Sigma pagination missing at page {page}")
        return 1, False
    current = nav.select_one('[aria-current="page"][data-index]')
    if not current or int(current["data-index"]) != page:
        raise RuntimeError(f"Sigma pagination did not advance to page {page}")
    last_button = nav.select_one('[aria-label^="last page, page "]')
    last = int(last_button["data-index"]) if last_button else max(
        int(x["data-index"]) for x in nav.select("[data-index]")
    )
    next_button = nav.select_one('[aria-label="next page"]')
    has_next = bool(next_button and not next_button.has_attr("disabled") and not next_button.has_attr("data-disabled"))
    if has_next != (page < last):
        raise RuntimeError(f"Sigma next button inconsistent at page {page}/{last}")
    return last, has_next


def sigma_cards(soup, category: str, depth: int) -> list[dict]:
    cards = []
    for anchor in soup.select('a.chakra-tooltip__trigger[href*="/en/item?id="]'):
        container = anchor.parent.parent
        current_price = container.select_one("p.font-bold")
        image = container.select_one('img[alt="Product Image"]')
        cards.append({
            "name": anchor.get_text(" ", strip=True),
            "product_url": urljoin("https://www.sigma-computer.com", anchor["href"]),
            "price": current_price.get_text(" ", strip=True) if current_price else None,
            "image_url": image.get("src") if image else None,
            "brand": None, "in_stock": None, "category": category, "depth": depth,
            "provider": "sigma",
        })
    return cards


def next_sigma_url(url: str, page: int) -> str:
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["page"] = str(page)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


class SigmaSpider(PartsSpider):
    name = "sigma"
    base_url = "https://www.sigma-computer.com/en"
    start_urls = [base_url]
    allowed_domains = {"sigma-computer.com"}

    async def parse(self, response: Response):
        try:
            self.check_response(response)
            seeds = discover_sigma(response.body)
            if self.categories:
                seeds = [seed for seed in seeds if seed.category in self.categories]
            if self.limit_categories:
                seeds = seeds[: self.limit_categories]
            self.discovered = seeds
            for seed in seeds:
                yield response.follow(seed.url, callback=self.parse_listing, meta={"seed": seed, "page": 1})
        except Exception as exc:
            self.errors.append(f"Sigma discovery: {exc}")
            yield None

    async def parse_listing(self, response: Response):
        try:
            self.check_response(response)
            seed = response.meta["seed"]
            page = response.meta["page"]
            soup = soup_of(response)
            cards = sigma_cards(soup, seed.category, seed.depth)
            self.check_page(seed.url, str(response.url), [c["product_url"] for c in cards], page)
            last, has_next = sigma_page(soup, page, len(cards))
            self.check_last_page(seed.url, last)
            for card in cards:
                yield response.follow(card["product_url"], callback=self.parse_detail,
                                      meta={"product": card}, dont_filter=True)
            if has_next and (self.limit_pages is None or page < self.limit_pages):
                yield response.follow(next_sigma_url(str(response.url), page + 1), callback=self.parse_listing,
                                      meta={"seed": seed, "page": page + 1})
            elif not has_next:
                self.finished_categories.add(seed.url)
        except Exception as exc:
            self.errors.append(f"Sigma listing {response.url}: {exc}")
            yield None

    async def parse_detail(self, response: Response):
        try:
            self.check_response(response)
            card = dict(response.meta["product"])
            soup = soup_of(response)
            ld = jsonld_fields(product_jsonld(soup, str(response.url), self.name))
            if not ld:
                raise RuntimeError("matching Product JSON-LD missing")
            visible_price = parse_price(card.get("price"))
            structured_price = parse_price(ld.get("price"))
            if visible_price is not None and structured_price is not None and visible_price != structured_price:
                raise RuntimeError(f"listing and Product JSON-LD prices disagree: {visible_price} vs {structured_price}")
            card["brand"] = ld.get("brand")
            card["in_stock"] = ld.get("in_stock")
            card["price"] = ld.get("price") or card.get("price")
            card["image_url"] = ld.get("image_url") or card.get("image_url")
            heading = soup.select_one("h1")
            if heading:
                card["name"] = heading.get_text(" ", strip=True)
            self.raw_count += 1
            yield card
        except Exception as exc:
            self.errors.append(f"Sigma detail {response.url}: {exc}")
            yield None
