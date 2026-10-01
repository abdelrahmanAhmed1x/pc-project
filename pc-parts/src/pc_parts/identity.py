"""Conservative, explainable identity evidence for retailer listings.

This module never treats a retailer SKU, a price, or title similarity as proof.
Unknown critical attributes remain unknown rather than being inferred.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property

RULE_VERSION = 1
STOP = {"new", "original", "with", "for", "the", "and", "gaming", "wireless",
        "black", "white", "blue", "red", "silver", "egp", "warranty", "years",
        "year", "gb", "tb", "hz", "inch", "ssd", "ram"}
COLORS = {"black", "white", "blue", "red", "silver", "gold", "purple", "green", "pink", "gray", "grey"}


def normalized(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def identifier(value: str | None) -> str | None:
    clean = re.sub(r"[^a-z0-9]", "", normalized(value))
    return clean or None


def title_tokens(title: str) -> set[str]:
    return {token for token in normalized(title).split() if len(token) >= 3 and token not in STOP}


def _first(pattern: str, title: str) -> str | None:
    match = re.search(pattern, title, re.I)
    return normalized(match.group(1)).replace(" ", "") if match else None


def attributes(category: str, title: str, variant: dict | None = None,
               specs: dict | None = None) -> dict[str, str]:
    # Explicit variant/specification values take priority over title parsing.
    text = " ".join(str(x) for x in (variant or {}).values()) + " " + title
    result: dict[str, str] = {}
    def put(field: str, pattern: str, source: str = text):
        value = _first(pattern, source)
        if value:
            result[field] = value

    if category == "cpu":
        put("cpu_model", r"\b((?:ryzen\s*[3579]\s*|core\s*(?:i[3579]|ultra\s*[3579])\s*[- ]?|threadripper\s*|athlon\s*|pentium\s*)[a-z0-9-]{3,})\b")
        put("package", r"\b(tray|box|boxed|mpk|oem)\b")
        if result.get("package") == "boxed":
            result["package"] = "box"
    elif category == "gpu":
        put("chip", r"\b((?:rtx|gtx|rx|arc)\s*[a-z]?\s*\d{3,4}\s*(?:ti|super|xt|xtx)?)\b")
        put("vram", r"\b(\d{1,2}\s*gb)\b")
        put("edition", r"\b(oc|non oc|white|b[tf]{2}|evo)\b")
    elif category == "motherboard":
        put("chipset", r"\b((?:b|x|z|h|a)\s*\d{3,4}\s*e?)\b")
        put("socket", r"\b((?:lga|am)\s*\d{1,4})\b")
    elif category == "ram":
        put("generation", r"\b(ddr[345])\b")
        put("speed", r"\b(?:ddr[345][ -]?)?(\d{4,5})\s*(?:mhz|mt/s|mtps)?\b")
        put("latency", r"\b(cl\s*\d{2})\b")
        put("kit", r"\b(\d\s*[x×]\s*\d{1,3}\s*gb)\b")
        put("capacity", r"\b(\d{1,3}\s*gb)\b")
        put("rgb", r"\b(rgb|argb)\b")
    elif category in {"ssd", "hdd"}:
        put("capacity", r"\b(\d+(?:\.\d+)?\s*(?:tb|gb))\b")
        put("interface", r"\b(nvme|sata|pcie\s*[345](?:\.0)?)\b")
        put("form_factor", r"\b(m\.?2|2\.?5|3\.?5)\b")
    elif category == "mobile_phones":
        sizes = re.findall(r"\b(\d+(?:\.\d+)?)\s*(tb|gb)\b", text, re.I)
        capacities = [(float(number) * (1024 if unit.casefold() == "tb" else 1),
                       normalized(number + unit)) for number, unit in sizes]
        capacities = [value for value in capacities if value[0] >= 64]
        if capacities:
            result["storage"] = max(capacities)[1]
        for key, value in (variant or {}).items():
            if normalized(str(key)) in {"storage", "capacity"}:
                explicit = _first(r"\b(\d+(?:\.\d+)?\s*(?:tb|gb))\b", str(value))
                if explicit:
                    result["storage"] = explicit
        put("generation", r"\b(iphone\s*\d{1,2}\s*(?:pro\s*max|pro|plus|mini)?|galaxy\s*[asz]\s*\d{1,3}\s*(?:ultra|plus|fe)?)\b")
        put("network", r"\b(4g|5g)\b")
        put("color", r"\b(" + "|".join(sorted(COLORS)) + r")\b")
    elif category == "laptops":
        put("cpu", r"\b((?:i[3579]-?\d{4,5}[a-z]{0,2}|ryzen\s*[3579]\s*\d{4}[a-z]{0,2}|core\s*ultra\s*[3579]\s*\d{3}[a-z]{0,2}))\b")
        put("gpu", r"\b((?:rtx|gtx|rx)\s*\d{3,4}\s*(?:ti|super|xt)?)\b")
        put("ram", r"\b(\d{1,3}\s*gb)\s*(?:ram|ddr[345])\b")
        put("storage", r"\b(\d+(?:\.\d+)?\s*(?:tb|gb))\s*(?:ssd|hdd|nvme)\b")
        put("display", r"\b(\d{2,3}(?:\.\d)?\s*(?:inch|\"))\b")
    elif category in {"headphones", "headsets", "earphones", "true_wireless_earbuds"}:
        put("generation", r"\b(\d(?:st|nd|rd|th)?\s*gen(?:eration)?)\b")
        put("color", r"\b(" + "|".join(sorted(COLORS)) + r")\b")
    elif category == "monitor":
        put("size", r"\b(\d{2}(?:\.\d)?\s*(?:inch|\"))\b")
        put("refresh", r"\b(\d{2,3}\s*hz)\b")
        put("resolution", r"\b(4k|qhd|fhd|\d{4}\s*[x×]\s*\d{3,4})\b")
    elif category == "power_supply":
        put("wattage", r"\b(\d{3,4}\s*w)\b")
    elif category == "cooling":
        put("radiator", r"\b(120|240|280|360|420)\s*mm\b")
        put("kind", r"\b(aio|liquid|air)\b")
    for key, value in (specs or {}).items():
        field = normalized(str(key)).replace(" ", "_")
        if field in {"model", "model_number", "manufacturer_model_number", "cpu", "gpu", "ram", "storage", "capacity", "speed", "latency", "generation", "wattage", "refresh", "resolution"}:
            result[field] = normalized(str(value))
    return result


CRITICAL = {
    "cpu": {"cpu_model", "package"},
    "gpu": {"chip", "vram", "edition"},
    "motherboard": {"chipset", "socket"},
    "ram": {"generation", "capacity", "kit", "speed", "latency", "rgb"},
    "ssd": {"capacity", "interface", "form_factor"}, "hdd": {"capacity", "interface", "form_factor"},
    "mobile_phones": {"generation", "storage", "network", "color"},
    "laptops": {"cpu", "gpu", "ram", "storage", "display"},
    "monitor": {"size", "refresh", "resolution"},
    "power_supply": {"wattage"}, "cooling": {"radiator", "kind"},
    "headphones": {"generation", "color"}, "headsets": {"generation", "color"},
    "earphones": {"generation", "color"}, "true_wireless_earbuds": {"generation", "color"},
}


@dataclass(frozen=True)
class Evidence:
    category: str
    brand: str | None
    title: str
    mpn: str | None = None
    gtin: str | None = None
    model_number: str | None = None
    variant: dict | None = None
    specifications: dict | None = None

    @cached_property
    def attrs(self) -> dict[str, str]:
        return attributes(self.category, self.title, self.variant, self.specifications)

    @cached_property
    def tokens(self) -> set[str]:
        return title_tokens(self.title)


def conflicts(a: Evidence, b: Evidence) -> list[str]:
    if a.category != b.category:
        return ["category"]
    if a.brand and b.brand and normalized(a.brand) != normalized(b.brand):
        return ["brand"]
    problems = []
    # Two explicit manufacturer identifiers for one exact variant must agree.
    for field in ("mpn", "gtin", "model_number"):
        left, right = identifier(getattr(a, field)), identifier(getattr(b, field))
        if left and right and left != right:
            problems.append(field)
    left, right = a.attrs, b.attrs
    for field in CRITICAL.get(a.category, set()):
        if left.get(field) and right.get(field) and left[field] != right[field]:
            problems.append(field)
    return problems


def candidate_score(a: Evidence, b: Evidence) -> float:
    if a.category != b.category or not a.brand or not b.brand or normalized(a.brand) != normalized(b.brand):
        return 0
    if identifier(a.gtin) and identifier(a.gtin) == identifier(b.gtin):
        return 1
    if identifier(a.mpn) and identifier(a.mpn) == identifier(b.mpn):
        return 1
    left, right = a.tokens, b.tokens
    if not left or not right:
        return 0
    score = len(left & right) / len(left | right)
    for field in ("cpu_model", "generation", "chip"):
        if a.attrs.get(field) and a.attrs.get(field) == b.attrs.get(field):
            score = max(score, 0.5)
    return score


def deterministic_verdict(a: Evidence, b: Evidence) -> str:
    problems = conflicts(a, b)
    if (a.category == b.category == "mobile_phones" and a.brand and b.brand
            and normalized(a.brand) == normalized(b.brand)
            and a.attrs.get("generation") and a.attrs.get("generation") == b.attrs.get("generation")
            and problems and set(problems) <= {"storage", "color", "mpn", "gtin"}):
        return "same_product_different_variant"
    if (a.category == b.category == "cpu" and a.brand and b.brand
            and normalized(a.brand) == normalized(b.brand)
            and a.attrs.get("cpu_model") and a.attrs.get("cpu_model") == b.attrs.get("cpu_model")
            and problems and set(problems) <= {"package", "mpn", "gtin"}):
        return "same_product_different_variant"
    if problems:
        return "different_product"
    if not a.brand or not b.brand:
        return "uncertain"
    if a.gtin and b.gtin and identifier(a.gtin) == identifier(b.gtin):
        return "same_exact_variant"
    if a.mpn and b.mpn and identifier(a.mpn) == identifier(b.mpn):
        return "same_exact_variant"
    if a.category == "cpu" and a.attrs.get("cpu_model") and a.attrs == b.attrs:
        return "same_exact_variant"
    return "uncertain"
