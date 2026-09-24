from pc_parts.spiders.opencart import OpenCartSpider


class ElnekhelySpider(OpenCartSpider):
    name = "elnekhely"
    base_url = "https://www.elnekhelytechnology.com/"
    start_urls = [base_url]
    allowed_domains = {"elnekhelytechnology.com"}
    detail_for_all = True
    # This product detail path is disallowed by the site's robots.txt.
    # Its listing card can still provide a product row without requesting the detail page.
    listing_only_paths = (
        "/power-supply/asus-rog-strix-1000w-gold-aura-80-plus-gold-fully-modular-power-supply",
    )
