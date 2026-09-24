from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    timezone: str
    crawl_delay_seconds: float
    min_products_per_provider: int
    max_delete_fraction: float

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            timezone=os.getenv("TZ", "Africa/Cairo"),
            crawl_delay_seconds=float(os.getenv("CRAWL_DELAY_SECONDS", "1")),
            min_products_per_provider=int(os.getenv("MIN_PRODUCTS_PER_PROVIDER", "10")),
            max_delete_fraction=float(os.getenv("MAX_DELETE_FRACTION", "0.35")),
        )
