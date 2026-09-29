from decimal import Decimal
import asyncio
import json
import pytest
from scrapling.spiders import Response

from pc_parts.models import CategorySeed
from pc_parts.normalization.categories import opencart_category
from pc_parts.normalization.products import canonical_url, clean_raw
from pc_parts.spiders.alfrensia import AlfrensiaSpider, alfrensia_last_page, alfrensia_product, alfrensia_seeds
from pc_parts.spiders.common import opencart_cards, soup_of
from pc_parts.spiders.compumarts import CompumartsSpider, compumarts_product, compumarts_seeds
from pc_parts.spiders import SPIDERS
from pc_parts.staging import Stage


def test_provider_registry_and_urls():
    assert set(SPIDERS) == {"sigma", "elnekhely", "elbadr", "alfrensia", "maximum", "compumarts"}
    assert canonical_url("https://alfrensia.com/en/product/cpu/?utm_source=test", "https://alfrensia.com", "alfrensia") == "https://alfrensia.com/en/product/cpu"
    assert canonical_url("https://maximumhardware.store/processors/cpu?utm_source=test", "https://maximumhardware.store", "maximum") == "https://maximumhardware.store/processors/cpu"
    assert canonical_url("https://compumarts.com/products/cpu?variant=123", "https://www.compumarts.com", "compumarts") == "https://www.compumarts.com/products/cpu"


def test_alfrensia_category_and_sale_price():
    assert alfrensia_last_page({"X-WP-TotalPages": "3"}) == 3
    slugs = ["processor", "graphics-card", "motherboard", "ram", "ssd", "hdd", "cases",
             "power-supply", "air-liquid-cooling", "case-fans"]
    seeds = alfrensia_seeds([{"id": i + 1, "slug": slug, "name": slug} for i, slug in enumerate(slugs)])
    assert len(seeds) == 10
    assert {seed.category for seed in seeds} == {"cpu", "gpu", "motherboard", "ram", "ssd", "hdd", "case", "power_supply", "cooling"}
    item = {
        "name": "ASUS &amp; AMD", "permalink": "https://alfrensia.com/en/product/part/",
        "brands": [{"name": "ASUS"}], "images": [{"src": "https://alfrensia.com/image.jpg"}],
        "prices": {"price": "419900", "regular_price": "480000", "sale_price": "419900",
                   "currency_code": "EGP", "currency_minor_unit": 2}, "is_in_stock": True,
    }
    product = alfrensia_product(item, CategorySeed("https://alfrensia.com/api", "cpu"))
    assert product["name"] == "ASUS & AMD"
    assert product["price"] == Decimal("4199")
    assert product["in_stock"] is True


def test_maximum_mapping_and_card_fields():
    assert opencart_category("maximum", "https://maximumhardware.store/hard-disks") == "hdd"
    html = '''<div class="main-products"><div class="product-layout"><div class="caption">
      <div class="stats"><span class="stat-1">Stock: In Stock</span>
      <span class="stat-2">Brand: <a>AMD</a></span></div>
      <div class="name"><a href="/processors/amd-cpu">AMD CPU</a></div>
      <div class="price"><span class="price-old">4,800 EGP</span>
      <span class="price-new">4,199 EGP</span></div></div></div></div>'''
    cards = opencart_cards(soup_of(html), "cpu", 1, "https://maximumhardware.store/", "maximum",
                           stock_selector=".stat-1", brand_selector=".stat-2 a")
    assert cards[0]["brand"] == "AMD"
    assert cards[0]["in_stock"] is True
    assert cards[0]["price"] == "4,199 EGP"


def test_compumarts_collection_and_available_variant():
    slugs = ["pc-parts-proccesor", "pc-parts-graphic-card", "pc-parts-mother-board",
             "pc-parts-ram-1", "storage-ssd", "storage-hdd", "pc-parts-computer-cases",
             "pc-parts-power-supply", "pc-parts-cooling-solutions", "computer-fan"]
    links = "".join(f'<a href="/collections/{slug}?sort_by=price-descending">{slug}</a>' for slug in slugs)
    seeds = compumarts_seeds(links)
    assert len(seeds) == 10
    item = {
        "title": "MSI &amp; GPU", "handle": "msi-gpu", "vendor": "MSI",
        "images": [{"src": "https://cdn.shopify.com/gpu.jpg"}],
        "variants": [
            {"available": False, "price": "1000.00"},
            {"available": True, "price": "4199.00", "compare_at_price": "4800.00"},
            {"available": True, "price": "4500.00"},
        ],
    }
    product = compumarts_product(item, CategorySeed("https://www.compumarts.com/collections/gpu", "gpu"))
    assert product["price"] == Decimal("4199.00")
    assert product["in_stock"] is True
    assert product["product_url"] == "https://www.compumarts.com/products/msi-gpu"
    assert compumarts_product({**item, "variants": []}, CategorySeed("https://www.compumarts.com/collections/gpu", "gpu"))["in_stock"] is None
    assert clean_raw({**product, "price": "1"}, "compumarts", "https://www.compumarts.com")["price"] is None
    with pytest.raises(ValueError, match="bundle"):
        compumarts_product({**item, "title": "Gaming PC Bundle"},
                           CategorySeed("https://www.compumarts.com/collections/gpu", "gpu"))


def test_placeholder_price_is_counted_and_kept_as_unknown():
    with Stage("compumarts", "https://www.compumarts.com/") as stage:
        stage.add({"name": "CPU", "category": "cpu", "brand": "AMD", "price": "1.00",
                   "in_stock": False, "product_url": "/products/cpu"})
        assert stage.finish() == 1
        assert stage.placeholder_count == 1
        assert stage.sample_by_category(1)[0][3] is None


def test_malformed_api_record_does_not_abort_page():
    alfrensia = AlfrensiaSpider()
    alf_seed = CategorySeed("https://alfrensia.com/api?page=1", "cpu")
    alfrensia.discovered = [alf_seed]
    alf_item = {"name": "AMD CPU", "permalink": "https://alfrensia.com/en/product/cpu/",
                "prices": {"price": "5000", "currency_code": "EGP", "currency_minor_unit": 0},
                "is_in_stock": True}
    alf_response = Response(alf_seed.url, json.dumps([None, alf_item]).encode(), 200, "OK",
                            {}, {"X-WP-TotalPages": "1"}, {}, meta={"seed": alf_seed, "page": 1})

    compumarts = CompumartsSpider()
    comp_seed = CategorySeed("https://www.compumarts.com/collections/cpu", "cpu")
    compumarts.discovered = [comp_seed]
    comp_item = {"title": "AMD CPU", "handle": "cpu", "vendor": "AMD",
                 "variants": [{"available": True, "price": "5000.00"}]}
    comp_response = Response(compumarts.listing_url(comp_seed, 1),
                             json.dumps({"products": [None, comp_item]}).encode(), 200, "OK",
                             {}, {}, {}, meta={"seed": comp_seed, "page": 1})

    async def parse(spider, response):
        return [item async for item in spider.parse_listing(response)]

    assert len(asyncio.run(parse(alfrensia, alf_response))) == 1
    assert len(asyncio.run(parse(compumarts, comp_response))) == 1
    assert not alfrensia.errors and not compumarts.errors
