from __future__ import annotations

from urllib.parse import urlsplit

CANONICAL_CATEGORIES = (
    "cpu", "gpu", "motherboard", "ram", "ssd", "hdd", "case", "power_supply", "cooling"
)

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
    path = urlsplit(url).path.rstrip("/").split("/")[-1].lower()
    return OPENCART_PATHS[provider].get(path)


def sigma_category(path: tuple[str, ...]) -> str | None:
    if not path or path[0] not in {"Hardware Components", "Storage"}:
        return None
    return SIGMA_LEAVES.get(path[-1])
