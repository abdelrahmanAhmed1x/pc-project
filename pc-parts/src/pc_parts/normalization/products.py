from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pc_parts.normalization.brands import normalize_brand


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
    }[provider]
    if parsed.hostname.lower() not in allowed:
        raise InvalidProduct(f"offsite product URL: {url!r}")
    host = {"sigma": "www.sigma-computer.com", "elnekhely": "www.elnekhelytechnology.com", "elbadr": "elbadrgroupeg.store"}[provider]
    path = parsed.path.rstrip("/") or "/"
    if provider == "sigma":
        identity = dict(parse_qsl(parsed.query)).get("id")
        if path != "/en/item" or not identity:
            raise InvalidProduct("Sigma item URL lacks id")
        query = urlencode({"id": identity})
    else:
        params = dict(parse_qsl(parsed.query))
        if path.endswith("/index.php") and params.get("route") == "product/product":
            product_id = params.get("product_id")
            if not product_id:
                raise InvalidProduct("OpenCart product URL lacks product_id")
            query = urlencode({"route": "product/product", "product_id": product_id})
        else:
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
    if category not in {"cpu", "gpu", "motherboard", "ram", "ssd", "hdd", "case", "power_supply", "cooling"}:
        raise InvalidProduct(f"unmapped category: {category!r}")
    url = canonical_url(raw.get("product_url"), base, provider)
    stock = raw.get("in_stock")
    if isinstance(stock, str):
        stock = parse_stock(stock)
    elif stock is not None and not isinstance(stock, bool):
        stock = None
    price = parse_price(raw.get("price"))
    if price is not None and price > Decimal("9999999999.99"):
        raise InvalidProduct("price exceeds NUMERIC(12,2)")
    return {
        "name": name, "category": category, "brand": normalize_brand(raw.get("brand")),
        "price": price, "in_stock": stock,
        "product_url": url, "image_url": absolute_image(raw.get("image_url"), base),
        "provider": provider, "currency": "EGP", "depth": int(raw.get("depth") or 0),
    }
