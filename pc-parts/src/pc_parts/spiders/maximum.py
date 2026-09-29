from pc_parts.spiders.opencart import OpenCartSpider


class MaximumSpider(OpenCartSpider):
    name = "maximum"
    base_url = "https://maximumhardware.store/"
    start_urls = [base_url]
    allowed_domains = {"maximumhardware.store"}
    detail_for_all = True
    stock_selector = ".stat-1"
    brand_selector = ".stat-2 a"
