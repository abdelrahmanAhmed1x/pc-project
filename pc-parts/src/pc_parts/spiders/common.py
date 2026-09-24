from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from scrapling.spiders import Response, Spider

from pc_parts.models import CategorySeed
from pc_parts.normalization.categories import CANONICAL_CATEGORIES, opencart_category
from pc_parts.normalization.products import canonical_url, parse_stock


def soup_of(response: Response | str | bytes) -> BeautifulSoup:
    body = response.body if isinstance(response, Response) else response
    return BeautifulSoup(body, "lxml")


def product_jsonld(soup: BeautifulSoup, url: str, provider: str) -> dict | None:
    candidates = []
    try:
        target = canonical_url(url, url, provider)
    except ValueError:
        return None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        entries = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in entries:
            if isinstance(item, dict) and "Product" in str(item.get("@type", "")):
                candidates.append(item)
    for item in candidates:
        offers = item.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        for possible in (item.get("url"), item.get("@id"), offers.get("url")):
            if not possible:
                continue
            try:
                candidate = canonical_url(possible, url, provider)
            except ValueError:
                continue
            if candidate == target or (provider != "sigma" and urlsplit(candidate).path.split("/")[-1] == urlsplit(target).path.split("/")[-1]):
                return item
    return None


def jsonld_fields(item: dict | None) -> dict:
    if not item:
        return {}
    offers = item.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    brand = item.get("brand")
    image = item.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    return {
        "brand": brand.get("name") if isinstance(brand, dict) else brand,
        "price": offers.get("price"),
        "in_stock": parse_stock(offers.get("availability")),
        "image_url": image,
    }


class PartsSpider(Spider):
    allowed_domains: set[str]
    robots_txt_obey = True
    concurrent_requests = 2
    concurrent_requests_per_domain = 2
    download_delay = 1.0
    logging_level = logging.INFO
    base_url: str

    def __init__(self, *, limit_pages: int | None = None, limit_categories: int | None = None,
                 categories: set[str] | None = None, delay: float = 1.0):
        super().__init__()
        self.limit_pages = limit_pages
        self.limit_categories = limit_categories
        self.categories = categories
        self.download_delay = delay
        self.errors: list[str] = []
        self.discovered: list[CategorySeed] = []
        self.finished_categories: set[str] = set()
        self.visited_pages: set[str] = set()
        self.page_signatures: dict[str, set[str]] = {}
        self.expected_last_pages: dict[str, int] = {}
        self.raw_count = 0
        self.failed_requests = 0
        self.robots_disallowed = 0

    async def on_close(self):
        # Spider.stats is only available while Scrapling's stream is active.
        self.failed_requests = self.stats.failed_requests_count
        self.robots_disallowed = self.stats.robots_disallowed_count

    async def on_error(self, request, error):
        self.errors.append(f"request failed {request.url}: {error}")

    def check_response(self, response: Response):
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {response.url}")

    def check_page(self, category: str, url: str, urls: list[str], page: int):
        if url in self.visited_pages:
            raise RuntimeError(f"pagination loop: {url}")
        self.visited_pages.add(url)
        if not urls:
            raise RuntimeError(f"zero products on {category} page {page}: {url}")
        signature = frozenset(urls)
        if signature in self.page_signatures.setdefault(category, set()):
            raise RuntimeError(f"repeated product page for {category}: {url}")
        self.page_signatures[category].add(signature)

    def check_last_page(self, category: str, last: int):
        expected = self.expected_last_pages.setdefault(category, last)
        if last != expected:
            raise RuntimeError(f"pagination total changed for {category}: {expected} -> {last}")

    def validate_complete(self):
        if self.errors:
            raise RuntimeError("; ".join(self.errors[:10]))
        if not self.discovered:
            raise RuntimeError("no approved categories discovered")
        expected = {seed.url for seed in self.discovered}
        if self.finished_categories != expected:
            raise RuntimeError(f"incomplete categories: {sorted(expected - self.finished_categories)}")
        if self.failed_requests or self.robots_disallowed:
            raise RuntimeError("failed or robots-disallowed requests during crawl")


def discover_opencart(html: str | bytes, provider: str, base: str) -> list[CategorySeed]:
    soup = soup_of(html)
    choices: dict[str, CategorySeed] = {}
    for anchor in soup.select("a[href]"):
        href = urljoin(base, anchor["href"])
        if urlsplit(href).hostname != urlsplit(base).hostname or urlsplit(href).query:
            continue
        category = opencart_category(provider, href)
        if category:
            seed = CategorySeed(href, category, len(urlsplit(href).path.strip("/").split("/")), anchor.get_text(" ", strip=True))
            current = choices.get(category)
            if current is None or (seed.depth, seed.url) < (current.depth, current.url):
                choices[category] = seed
    missing = set(CANONICAL_CATEGORIES) - set(choices)
    if missing:
        raise RuntimeError(f"required category links missing: {sorted(missing)}")
    return [choices[cat] for cat in CANONICAL_CATEGORIES]


def opencart_page(soup: BeautifulSoup, page: int) -> tuple[str | None, int]:
    nav = soup.select_one("ul.pagination")
    summary = soup.find(string=re.compile(r"Showing\s+\d+\s+to\s+\d+\s+of\s+\d+\s+\(\d+\s+Pages?\)", re.I))
    summary_last = int(re.search(r"\((\d+)\s+Pages?\)", str(summary), re.I).group(1)) if summary else None
    if nav is None:
        if page > 1 or (summary_last and summary_last > 1):
            raise RuntimeError(f"missing pagination at page {page}")
        return None, page
    active = nav.select_one("li.active")
    if active and active.get_text(" ", strip=True).isdigit() and int(active.get_text(" ", strip=True)) != page:
        raise RuntimeError(f"pagination active page mismatch: expected {page}")
    nums = [int(a.get_text(" ", strip=True)) for a in nav.select("a") if a.get_text(" ", strip=True).isdigit()]
    last = max([page] + nums)
    for a in nav.select("a[href]"):
        if a.get_text(" ", strip=True).endswith("|"):
            match = re.search(r"page=(\d+)", a["href"])
            if match:
                last = max(last, int(match.group(1)))
    if summary_last is not None and last != summary_last:
        raise RuntimeError(f"pagination summary disagrees with links: {last} vs {summary_last}")
    next_link = nav.select_one("a.next[href]")
    if page < last and not next_link:
        raise RuntimeError(f"missing next pagination link at page {page}/{last}")
    if page == last and next_link:
        raise RuntimeError("next link present at reported final page")
    return next_link["href"] if next_link else None, last


def opencart_explicitly_empty(soup: BeautifulSoup) -> bool:
    return bool(soup.find(string=lambda value: bool(value) and
                          value.strip() == "There are no products to list in this category."))


def opencart_cards(soup: BeautifulSoup, category: str, depth: int, base: str, provider: str) -> list[dict]:
    products = []
    for card in soup.select(".main-products .product-layout"):
        anchor = card.select_one(".caption .name a[href]")
        if not anchor:
            products.append({"name": "", "product_url": "", "category": category, "depth": depth})
            continue
        new_price = card.select_one(".caption .price .price-new")
        normal_price = card.select_one(".caption .price .price-normal")
        price = (new_price or normal_price)
        brand = card.select_one(".caption .stats .stat-1 a")
        stock = card.select_one(".caption .stats .stat-2")
        image = card.select_one(".image-group .product-img img.img-first") or card.select_one(".image-group .product-img img")
        from_label = any("from" in label.get_text(" ", strip=True).casefold()
                         for label in card.select(".product-label"))
        products.append({
            "name": anchor.get_text(" ", strip=True), "product_url": urljoin(base, anchor["href"]),
            "category": category, "depth": depth, "brand": brand.get_text(" ", strip=True) if brand else None,
            "price": price.get_text(" ", strip=True) if price else None,
            "price_label": "from" if from_label or (price and "from" in price.get_text(" ", strip=True).casefold()) else None,
            "in_stock": parse_stock(stock.get_text(" ", strip=True)) if stock else None,
            "image_url": image.get("src") or image.get("data-src") if image else None,
            "provider": provider,
        })
    return products
