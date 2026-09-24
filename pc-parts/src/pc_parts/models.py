from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CategorySeed:
    url: str
    category: str
    depth: int = 0
    label: str = ""


@dataclass(frozen=True)
class Product:
    name: str
    category: str
    brand: str | None
    price: Decimal | None
    in_stock: bool | None
    product_url: str
    image_url: str | None
    provider: str
    currency: str = "EGP"
