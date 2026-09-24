from __future__ import annotations

import re

ALIASES = {
    "g.skill": "G.Skill",
    "g skill": "G.Skill",
    "asus": "ASUS",
    "amd": "AMD",
    "intel": "Intel",
    "msi": "MSI",
    "gigabyte": "Gigabyte",
    "kingston": "Kingston",
    "addlink": "Addlink",
    "cooler master": "Cooler Master",
    "nvidia": "NVIDIA",
}


def normalize_brand(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    clean = re.sub(r"\s+", " ", value.strip())
    return ALIASES.get(clean.casefold(), clean.casefold())
