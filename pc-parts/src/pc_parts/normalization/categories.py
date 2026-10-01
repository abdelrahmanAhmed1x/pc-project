from __future__ import annotations

import re
from urllib.parse import urlsplit

CANONICAL_CATEGORIES = (
    "cpu", "gpu", "motherboard", "ram", "ssd", "hdd", "case", "power_supply", "cooling",
    "monitor", "accessories", "laptops", "mobile_phones", "headphones", "headsets",
    "earphones", "true_wireless_earbuds",
)
PC_PART_CATEGORIES = CANONICAL_CATEGORIES[:11]


def audio_type(name: str, proposed: str) -> str:
    name = name.casefold()
    if re.search(r"airpods max|over[- ]ear|on[- ]ear|headphones?", name) and not re.search(r"in[- ]ear|earbuds?|tws|true wireless", name):
        return "headsets" if re.search(r"gaming headset|gaming headphone|headset|boom mic", name) else "headphones"
    if re.search(r"headset|gaming headphone", name):
        return "headsets"
    if re.search(r"airpods(?! max)|earbuds?|tws|true wireless|studio buds|solo buds", name):
        return "true_wireless_earbuds"
    if re.search(r"earpods|wired earphone|in[- ]ear|earphones?|neckband|necklace", name):
        return "earphones"
    return proposed

OPENCART_PATHS = {
    "elnekhely": {
        "processors": "cpu", "graphics-card": "gpu", "motherboards": "motherboard",
        "ram": "ram", "ssd": "ssd", "hdd": "hdd", "cases": "case",
        "power-supply": "power_supply", "fans-coolers": "cooling",
    },
    "elbadr": {
        "cpu": "cpu", "vga": "gpu", "motherboard": "motherboard",
        "ram": "ram", "ssd": "ssd", "hdd": "hdd", "cases": "case",
        "power-supply": "power_supply", "cooling": "cooling",
    },
    "maximum": {
        "processors": "cpu", "graphic-card": "gpu", "motherboards": "motherboard",
        "memory": "ram", "ssd": "ssd", "hard-disks": "hdd", "cases": "case",
        "power-supply": "power_supply", "fans-pc-cooling": "cooling",
    },
}

SIGMA_LEAVES = {
    "Intel CPU": "cpu", "AMD CPU": "cpu",
    "Intel Motherboard": "motherboard", "AMD Motherboard": "motherboard",
    "PC Memory": "ram", "Laptop Memory": "ram",
    "Nvidia GeForce": "gpu", "AMD RADEON": "gpu",
    "AIR Cooler": "cooling", "Liquid Cooler": "cooling", "Fans": "cooling",
    "Mini Tower": "case", "Mid Tower": "case", "Full Tower": "case",
    "Non modular": "power_supply", "Sime modular": "power_supply", "Full modular": "power_supply",
    "Internal SSD": "ssd", "Internal HDD": "hdd",
}


def opencart_category(provider: str, url: str) -> str | None:
    path = urlsplit(url).path.rstrip("/").lower()
    slug = path.split("/")[-1]
    if provider == "maximum":
        if path == "/monitors" or path.startswith("/monitors/"):
            return "monitor"
        if (path == "/accessories-1" or path.startswith("/accessories-1/")
                or slug in {"keyboard-mouse", "headphones-speakers"}):
            return "accessories"
    elif provider == "elbadr":
        if path in {"/headphones", "/accessories/headphones"}:
            return "headphones"
        if path == "/laptop":
            return "laptops"
        if path == "/monitors" or path.startswith("/monitors/"):
            return "monitor"
        if path == "/accessories" or path.startswith("/accessories/"):
            return "accessories"
    elif provider == "elnekhely":
        if path == "/monitors":
            return "monitor"
        if path == "/accessories":
            return "accessories"
        if path == "/laptop":
            return "laptops"
    return OPENCART_PATHS[provider].get(slug)


def sigma_category(path: tuple[str, ...]) -> str | None:
    if path and path[0] == "Laptops":
        return "laptops" if len(path) == 1 else None
    if path and path[-1] == "Headphone" and path[0] == "Accessories":
        return "headphones"
    if path and path[-1] == "Studio Headphones":
        return "headphones"
    if path and path[0] == "Monitor":
        return "monitor" if len(path) == 1 else None
    if path and path[0] == "Accessories":
        return "accessories" if len(path) == 1 else None
    if not path or path[0] not in {"Hardware Components", "Storage"}:
        return None
    return SIGMA_LEAVES.get(path[-1])
