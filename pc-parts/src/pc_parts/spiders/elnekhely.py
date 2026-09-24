from pc_parts.spiders.opencart import OpenCartSpider


class ElnekhelySpider(OpenCartSpider):
    name = "elnekhely"
    base_url = "https://www.elnekhelytechnology.com/"
    start_urls = [base_url]
    allowed_domains = {"elnekhelytechnology.com"}
    detail_for_all = True
