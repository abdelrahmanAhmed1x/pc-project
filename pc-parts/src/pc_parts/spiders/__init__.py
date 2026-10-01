from pc_parts.spiders.elbadr import ElbadrSpider
from pc_parts.spiders.elnekhely import ElnekhelySpider
from pc_parts.spiders.sigma import SigmaSpider
from pc_parts.spiders.alfrensia import AlfrensiaSpider
from pc_parts.spiders.maximum import MaximumSpider
from pc_parts.spiders.compumarts import CompumartsSpider
from pc_parts.spiders.shopify_tech import Dream2000Spider, TradelineSpider
from pc_parts.spiders.switchplus import SwitchPlusSpider
from pc_parts.spiders.twob import TwoBSpider

SPIDERS = {
    "sigma": SigmaSpider, "elnekhely": ElnekhelySpider, "elbadr": ElbadrSpider,
    "alfrensia": AlfrensiaSpider, "maximum": MaximumSpider, "compumarts": CompumartsSpider,
    "dream2000": Dream2000Spider, "tradeline": TradelineSpider,
    "twob": TwoBSpider, "switchplus": SwitchPlusSpider,
}

# Switch Plus currently reports all sampled stock as unavailable and its API
# began rate-limiting repeated requests. Keep it opt-in until the stock and
# access contract are confirmed against the storefront.
DEFAULT_PROVIDERS = tuple(name for name in SPIDERS if name != "switchplus")
