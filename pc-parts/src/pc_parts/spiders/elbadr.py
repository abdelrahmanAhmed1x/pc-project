from pc_parts.spiders.opencart import OpenCartSpider


class ElbadrSpider(OpenCartSpider):
    name = "elbadr"
    base_url = "https://elbadrgroupeg.store/"
    start_urls = [base_url]
    allowed_domains = {"elbadrgroupeg.store"}
    detail_for_all = True
