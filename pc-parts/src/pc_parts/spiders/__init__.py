from pc_parts.spiders.elbadr import ElbadrSpider
from pc_parts.spiders.elnekhely import ElnekhelySpider
from pc_parts.spiders.sigma import SigmaSpider
from pc_parts.spiders.alfrensia import AlfrensiaSpider
from pc_parts.spiders.maximum import MaximumSpider
from pc_parts.spiders.compumarts import CompumartsSpider

SPIDERS = {
    "sigma": SigmaSpider, "elnekhely": ElnekhelySpider, "elbadr": ElbadrSpider,
    "alfrensia": AlfrensiaSpider, "maximum": MaximumSpider, "compumarts": CompumartsSpider,
}
