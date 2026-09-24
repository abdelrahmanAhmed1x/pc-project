import asyncio
from pathlib import Path

import pytest
from scrapling.spiders import Request, Response

from pc_parts.normalization.brands import normalize_brand
from pc_parts.models import CategorySeed
from pc_parts.normalization.categories import sigma_category
from pc_parts.normalization.products import canonical_url, parse_price, parse_stock
from pc_parts.spiders.common import (
    discover_opencart, jsonld_fields, opencart_cards, opencart_page,
    opencart_explicitly_empty, product_jsonld, soup_of,
)
from pc_parts.spiders.sigma import discover_sigma, sigma_cards, sigma_page
from pc_parts.spiders.elbadr import ElbadrSpider
from pc_parts.spiders.elnekhely import ElnekhelySpider
from pc_parts.spiders.sigma import SigmaSpider

FIXTURES = Path(__file__).parent / "fixtures"


def page(name):
    return soup_of((FIXTURES / name).read_bytes())


def test_category_discovery_and_mapping():
    for provider, prefix, base in (
        ("elnekhely", "elnek", "https://www.elnekhelytechnology.com/"),
        ("elbadr", "elbadr", "https://elbadrgroupeg.store/"),
    ):
        seeds = discover_opencart((FIXTURES / f"{prefix}_home.html").read_bytes(), provider, base)
        assert {s.category for s in seeds} == {
            "cpu", "gpu", "motherboard", "ram", "ssd", "hdd", "case", "power_supply", "cooling"
        }
    sigma = discover_sigma((FIXTURES / "sigma_home.html").read_bytes())
    assert len(sigma) == 19
    assert {s.category for s in sigma} == {s.category for s in seeds}
    assert all("VGA Holder" not in s.label for s in sigma)
    assert sigma_category(("Hardware Components", "Graphic Card & Accessories", "VGA Holder")) is None


def test_pagination_advances_and_terminates():
    first = page("sigma_cpu1.html")
    second = page("sigma_cpu2.html")
    last = page("sigma_cpu8.html")
    assert sigma_page(first, 1) == (8, True)
    assert sigma_page(second, 2) == (8, True)
    assert sigma_page(last, 8) == (8, False)
    assert {x["product_url"] for x in sigma_cards(first, "cpu", 3)} != {
        x["product_url"] for x in sigma_cards(second, "cpu", 3)
    }
    with pytest.raises(RuntimeError, match="did not advance"):
        sigma_page(first, 2)
    assert opencart_page(page("elnek_ram.html"), 1)[0].endswith("page=2")
    assert opencart_page(page("elnek_ram2.html"), 2)[0].endswith("page=3")
    assert opencart_page(page("elnek_ram4.html"), 4) == (None, 4)
    assert "path=18&page=2" in opencart_page(page("elbadr_ram.html"), 1)[0]
    assert opencart_page(page("elbadr_ram18.html"), 18) == (None, 18)
    final_open_cart = soup_of('<ul class="pagination"><li><a href="/ram?page=3">3</a></li><li class="active"><span>4</span></li></ul>')
    assert opencart_page(final_open_cart, 4) == (None, 4)
    with pytest.raises(RuntimeError, match="missing next"):
        opencart_page(soup_of('<ul class="pagination"><li class="active"><span>1</span></li><li><a href="/ram?page=2">2</a></li></ul>'), 1)


def test_cards_prices_and_from_label():
    elnek = opencart_cards(page("elnek_ram.html"), "ram", 1,
                           "https://www.elnekhelytechnology.com/", "elnekhely")
    assert elnek[0]["name"].startswith("G.SKILL")
    assert elnek[0]["price_label"] == "from"
    assert parse_price(elnek[0]["price"]) == 34999
    assert elnek[0]["in_stock"] is True
    elbadr = opencart_cards(page("elbadr_ram.html"), "ram", 1,
                            "https://elbadrgroupeg.store/", "elbadr")
    assert elbadr[0]["brand"] == "addlink"
    assert elbadr[0]["in_stock"] is None
    synthetic = soup_of('''<div class="main-products"><div class="product-layout"><div class="caption">
      <div class="name"><a href="/part">Part</a></div><div class="price">
      <span class="price-old">9,000 EGP</span><span class="price-new">7,000 EGP</span></div>
      </div></div></div>''')
    assert parse_price(opencart_cards(synthetic, "ram", 1, "https://elbadrgroupeg.store", "elbadr")[0]["price"]) == 7000
    assert sigma_cards(page("sigma_cpu1.html"), "cpu", 3)[0]["price"].startswith("14799")


def test_confirmed_empty_category_is_distinct_from_parser_failure():
    empty = page("elnek_hdd_empty.html")
    assert opencart_explicitly_empty(empty)
    assert opencart_cards(empty, "hdd", 1, "https://www.elnekhelytechnology.com", "elnekhely") == []

    async def parse(html):
        spider = ElnekhelySpider()
        seed = CategorySeed("https://www.elnekhelytechnology.com/hdd", "hdd", 1, "HDD")
        spider.discovered = [seed]
        response = Response(seed.url, html, 200, "OK", {}, {}, {}, meta={"seed": seed, "page": 1})
        _ = [item async for item in spider.parse_listing(response)]
        return spider

    accepted = asyncio.run(parse((FIXTURES / "elnek_hdd_empty.html").read_bytes()))
    accepted.validate_complete()
    failed = asyncio.run(parse(b'<html><div class="main-products"></div></html>'))
    assert failed.errors and "zero products" in failed.errors[0]


def test_product_jsonld_matches_current_detail_and_stock():
    sigma = page("sigma_detail.html")
    sigma_url = "https://www.sigma-computer.com/en/item?id=amd-ryzen-7-9700x-8c16t-38ghz55ghz-32mb-65w-tdp-socket-am5-lga-1718-trayfan-bn9kn1xohmvc"
    item = product_jsonld(sigma, sigma_url, "sigma")
    assert jsonld_fields(item)["brand"] == "AMD"
    assert jsonld_fields(item)["in_stock"] is True
    elbadr = page("elbadr_detail.html")
    item = product_jsonld(elbadr, "https://elbadrgroupeg.store/addlink-16gb-ddr5-5600mhz-cl46-desktop-memory", "elbadr")
    assert jsonld_fields(item)["price"] == 10500
    assert parse_stock(elbadr.select_one(".product-stock").get_text(" ", strip=True)) is True
    assert parse_stock("Stock: Out of Stock") is False
    assert parse_stock("Ask for availability") is None
    wrong = soup_of('''<script type="application/ld+json">{"@type":"Product","url":"https://elbadrgroupeg.store/other","offers":{"price":1}}</script>
      <script type="application/ld+json">{"@type":"Product","url":"https://elbadrgroupeg.store/right","offers":{"price":2}}</script>''')
    assert jsonld_fields(product_jsonld(wrong, "https://elbadrgroupeg.store/right", "elbadr"))["price"] == 2


def test_brand_and_url_normalization():
    assert normalize_brand("  G.skill  ") == normalize_brand("G.Skill") == "G.Skill"
    assert normalize_brand("  Corsair ") == normalize_brand("CORSAIR") == "corsair"
    assert normalize_brand("AMD") != normalize_brand("Intel")
    assert canonical_url("/en/item?utm_source=x&id=abc&ref=y", "https://www.sigma-computer.com/en", "sigma") == "https://www.sigma-computer.com/en/item?id=abc"
    assert canonical_url("/ram/test?utm_source=x", "https://www.elnekhelytechnology.com", "elnekhely") == "https://www.elnekhelytechnology.com/ram/test"
    assert canonical_url("/index.php?route=product/product&product_id=123&utm_source=x", "https://elbadrgroupeg.store", "elbadr") == "https://elbadrgroupeg.store/index.php?route=product%2Fproduct&product_id=123"


def test_detail_callbacks_and_fallbacks():
    async def extract(spider, fixture, url, card):
        response = Response(url, (FIXTURES / fixture).read_bytes(), 200, "OK", {}, {}, {},
                            meta={"product": card})
        return [item async for item in spider.parse_detail(response) if item]

    elnek_url = "https://www.elnekhelytechnology.com/ram/g-skill-ddr5-32gb-2x16gb-6400mt-s-cl30-desktop-memory-kit-–-amd-expo-ready-dual-channel-high-performance-ram"
    elnek = asyncio.run(extract(ElnekhelySpider(), "elnek_detail.html", elnek_url,
                               {"name": "RAM", "product_url": elnek_url.replace("/ram/", "/other/"), "in_stock": None,
                                "brand": None, "price": None, "category": "ram"}))
    assert elnek[0]["in_stock"] is True and elnek[0]["brand"] == "G.skill"
    assert elnek[0]["product_url"] == elnek_url
    elbadr_url = "https://elbadrgroupeg.store/addlink-16gb-ddr5-5600mhz-cl46-desktop-memory"
    elbadr = asyncio.run(extract(ElbadrSpider(), "elbadr_detail.html", elbadr_url,
                                {"name": "RAM", "product_url": elbadr_url, "in_stock": None,
                                 "brand": "Addlink", "price": "10,500 EGP", "category": "ram"}))
    assert elbadr[0]["in_stock"] is True
    sigma_url = "https://www.sigma-computer.com/en/item?id=amd-ryzen-7-9700x-8c16t-38ghz55ghz-32mb-65w-tdp-socket-am5-lga-1718-trayfan-bn9kn1xohmvc"
    sigma = asyncio.run(extract(SigmaSpider(), "sigma_detail.html", sigma_url,
                               {"name": "CPU", "product_url": sigma_url, "price": None,
                                "category": "cpu"}))
    assert sigma[0]["brand"] == "AMD" and sigma[0]["in_stock"] is True


def test_elnekhely_robots_disallowed_detail_uses_listing_card():
    spider = ElnekhelySpider()
    blocked_path = spider.listing_only_paths[0]
    allowed_path = "/power-supply/another-power-supply"
    listing_url = "https://www.elnekhelytechnology.com/power-supply"
    response = Response(
        listing_url,
        (f'<div class="main-products">'
         f'<div class="product-layout"><div class="caption"><div class="name">'
         f'<a href="{blocked_path}">Blocked detail product</a></div></div></div>'
         f'<div class="product-layout"><div class="caption"><div class="name">'
         f'<a href="{allowed_path}">Allowed detail product</a></div></div></div>'
         f'</div>').encode(),
        200, "OK", {}, {}, {},
        meta={"seed": CategorySeed(listing_url, "power_supply"), "page": 1},
    )
    response.request = Request(listing_url)

    async def parse():
        return [item async for item in spider.parse_listing(response) if item]

    items = asyncio.run(parse())
    assert items[0]["name"] == "Blocked detail product"
    assert items[0]["product_url"].endswith(blocked_path)
    assert spider.raw_count == 1
    assert len(items) == 2
    assert str(items[1].url).endswith(allowed_path)
    assert spider.finished_categories == {listing_url}
