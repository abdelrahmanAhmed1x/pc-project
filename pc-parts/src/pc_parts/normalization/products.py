from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pc_parts.normalization.brands import normalize_brand
from pc_parts.normalization.categories import CANONICAL_CATEGORIES, audio_type, storage_type


class InvalidProduct(ValueError):
    pass


def canonical_url(url: str | None, base: str, provider: str) -> str:
    if not url or not str(url).strip():
        raise InvalidProduct("missing product URL")
    absolute = urljoin(base, str(url).strip())
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidProduct(f"invalid product URL: {url!r}")
    allowed = {
        "sigma": {"sigma-computer.com", "www.sigma-computer.com"},
        "elnekhely": {"www.elnekhelytechnology.com", "elnekhelytechnology.com"},
        "elbadr": {"elbadrgroupeg.store", "www.elbadrgroupeg.store"},
        "alfrensia": {"alfrensia.com", "www.alfrensia.com"},
        "maximum": {"maximumhardware.store", "www.maximumhardware.store"},
        "compumarts": {"compumarts.com", "www.compumarts.com"},
        "dream2000": {"dream2000.com", "www.dream2000.com"},
        "tradeline": {"tradelinestores.com", "www.tradelinestores.com"},
        "switchplus": {"switchpluseg.com", "www.switchpluseg.com"},
        "twob": {"2b.com.eg", "www.2b.com.eg"},
        "raya": {"rayashop.com", "www.rayashop.com"},
    }[provider]
    if parsed.hostname.lower() not in allowed:
        raise InvalidProduct(f"offsite product URL: {url!r}")
    host = {
        "sigma": "www.sigma-computer.com", "elnekhely": "www.elnekhelytechnology.com",
        "elbadr": "elbadrgroupeg.store", "alfrensia": "alfrensia.com",
        "maximum": "maximumhardware.store", "compumarts": "www.compumarts.com",
        "dream2000": "dream2000.com", "tradeline": "tradelinestores.com",
        "switchplus": "switchpluseg.com", "twob": "2b.com.eg",
        "raya": "www.rayashop.com",
    }[provider]
    path = parsed.path.rstrip("/") or "/"
    if provider == "sigma":
        identity = dict(parse_qsl(parsed.query)).get("id")
        if path != "/en/item" or not identity:
            raise InvalidProduct("Sigma item URL lacks id")
        query = urlencode({"id": identity})
    elif provider in {"elnekhely", "elbadr", "maximum"}:
        params = dict(parse_qsl(parsed.query))
        if path.endswith("/index.php") and params.get("route") == "product/product":
            product_id = params.get("product_id")
            if not product_id:
                raise InvalidProduct("OpenCart product URL lacks product_id")
            query = urlencode({"route": "product/product", "product_id": product_id})
        else:
            query = ""
    else:
        if provider == "alfrensia" and not path.startswith("/en/product/"):
            raise InvalidProduct("Alfrensia URL is not a product page")
        if provider == "compumarts" and not path.startswith("/products/"):
            raise InvalidProduct("Compumarts URL is not a product page")
        if provider in {"dream2000", "tradeline"} and not path.startswith("/products/"):
            raise InvalidProduct("Shopify URL is not a product page")
        if provider == "switchplus" and not re.fullmatch(r"/item/\d+", path):
            raise InvalidProduct("Switch Plus URL is not an item page")
        if provider == "twob" and (not path.startswith("/en/") or not path.endswith(".html")):
            raise InvalidProduct("2B URL is not a product page")
        if provider == "raya" and not path.startswith("/en/"):
            raise InvalidProduct("Raya URL is not a product page")
        query = ""
    return urlunsplit(("https", host, path, query, ""))


def absolute_image(url: str | None, base: str) -> str | None:
    if not url:
        return None
    parsed = urlsplit(urljoin(base, url))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")) if parsed.scheme in {"http", "https"} else None


def parse_price(value: str | int | Decimal | None) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    clean = str(value).replace(",", "")
    match = re.search(r"\d+(?:\.\d{1,2})?", clean)
    if not match:
        return None
    try:
        amount = Decimal(match.group()).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return amount if amount >= 0 else None


def parse_stock(value: str | None) -> bool | None:
    if not value:
        return None
    lower = value.casefold()
    if "outofstock" in lower:
        return False
    if "instock" in lower:
        return True
    if any(x in lower for x in ("out of stock", "not in stock", "sold out", "unavailable", "not available")):
        return False
    if any(x in lower for x in ("in stock", "available")):
        return True
    return None


def clean_raw(raw: dict, provider: str, base: str) -> dict:
    name = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()
    if not name:
        raise InvalidProduct("missing product name")
    category = raw.get("category")
    if category not in CANONICAL_CATEGORIES:
        raise InvalidProduct(f"unmapped category: {category!r}")
    if category in {"headphones", "headsets", "earphones", "true_wireless_earbuds"}:
        category = audio_type(name, category)
    elif category in {"ssd", "hdd"}:
        category = storage_type(name, category)
    elif category == "accessories" and not re.search(r"\b(stand|holder|mount|case|cover|adapter|cable|protector)\b", name, re.I):
        category = audio_type(name, category)
    url = canonical_url(raw.get("product_url"), base, provider)
    stock = raw.get("in_stock")
    if isinstance(stock, str):
        stock = parse_stock(stock)
    elif stock is not None and not isinstance(stock, bool):
        stock = None
    price = parse_price(raw.get("price"))
    currency = raw.get("currency") or "EGP"
    if currency != "EGP":
        raise InvalidProduct(f"unsupported currency: {currency!r}")
    raw_price = raw.get("price")
    price_status = raw.get("price_status")
    if price is not None and price <= 2:
        price = None
        price_status = "placeholder"
    elif price is None:
        price_status = price_status if price_status in {"not_found", "price_on_request"} else "not_found"
    else:
        price_status = "known"
    if price is not None and price > Decimal("9999999999.99"):
        raise InvalidProduct("price exceeds NUMERIC(12,2)")
    condition = raw.get("condition")
    if not condition:
        if re.search(r"\b(refurbished|renewed|open[ -]?box)\b", name, re.I):
            condition = "refurbished"
        elif re.search(r"\b(used|pre[ -]?owned)\b", name, re.I):
            condition = "used"
        else:
            condition = "new"
    return {
        "name": name, "category": category, "brand": normalize_brand(raw.get("brand")),
        "price": price, "in_stock": stock,
        "product_url": url, "image_url": absolute_image(raw.get("image_url"), base),
        "provider": provider, "currency": currency, "depth": int(raw.get("depth") or 0),
        "price_status": price_status, "raw_price_text": str(raw_price) if raw_price is not None else None,
        "old_price": parse_price(raw.get("old_price")),
        "provider_product_id": str(raw["provider_product_id"]) if raw.get("provider_product_id") is not None else None,
        "provider_variant_id": str(raw["provider_variant_id"]) if raw.get("provider_variant_id") is not None else None,
        "sku": str(raw["sku"]).strip() if raw.get("sku") else None,
        "model_number": str(raw["model_number"]).strip() if raw.get("model_number") else None,
        "manufacturer_part_number": str(raw["manufacturer_part_number"]).strip() if raw.get("manufacturer_part_number") else None,
        "gtin": str(raw["gtin"]).strip() if raw.get("gtin") else None,
        "variant": raw.get("variant") or {}, "specifications": raw.get("specifications") or {},
        "seller_id": str(raw["seller_id"]) if raw.get("seller_id") else None,
        "condition": condition, "warranty": raw.get("warranty"),
    }
