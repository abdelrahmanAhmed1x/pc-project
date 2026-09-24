from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import pandas as pd

from pc_parts.normalization.products import InvalidProduct, clean_raw


class Stage:
    """Bounded Pandas cleanup followed by disk-backed temporary DuckDB staging."""

    def __init__(self, provider: str, base_url: str, batch_size: int = 500):
        self.provider = provider
        self.base_url = base_url
        self.batch_size = batch_size
        self._tmp = tempfile.TemporaryDirectory(prefix="pc-parts-")
        self.db = duckdb.connect(str(Path(self._tmp.name) / "stage.duckdb"))
        self.db.execute("SET memory_limit='256MB'")
        self.db.execute("""
            CREATE TABLE raw_products (
              name VARCHAR, category VARCHAR, brand VARCHAR, price DECIMAL(12,2),
              in_stock BOOLEAN, product_url VARCHAR, image_url VARCHAR,
              provider VARCHAR, currency VARCHAR, depth INTEGER
            )
        """)
        self.db.execute("CREATE TABLE category_priority (category VARCHAR PRIMARY KEY, rank INTEGER)")
        self.db.executemany("INSERT INTO category_priority VALUES (?, ?)", [
            (category, rank) for rank, category in enumerate(
                ("cpu", "gpu", "motherboard", "ram", "ssd", "hdd", "case", "power_supply", "cooling"), 1
            )
        ])
        self._buffer: list[dict] = []
        self.invalid_count = 0
        self.invalid_examples: list[str] = []
        self.accepted_count = 0

    def add(self, raw: dict):
        self._buffer.append(raw)
        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self._buffer:
            return
        frame = pd.DataFrame.from_records(self._buffer)
        self._buffer.clear()
        for column in ("name", "brand"):
            if column in frame:
                frame[column] = frame[column].astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
        frame = frame.astype(object).where(pd.notna(frame), None)
        rows = []
        for raw in frame.to_dict("records"):
            try:
                item = clean_raw(raw, self.provider, self.base_url)
            except (InvalidProduct, ValueError) as exc:
                self.invalid_count += 1
                if len(self.invalid_examples) < 20:
                    self.invalid_examples.append(f"{raw.get('product_url')!r}: {exc}")
                continue
            rows.append(tuple(item[key] for key in (
                "name", "category", "brand", "price", "in_stock", "product_url",
                "image_url", "provider", "currency", "depth"
            )))
        if rows:
            self.db.executemany("INSERT INTO raw_products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            self.accepted_count += len(rows)

    def finish(self) -> int:
        self.flush()
        return self.db.execute("SELECT COUNT(*) FROM (" + self.dedup_sql() + ")").fetchone()[0]

    @staticmethod
    def dedup_sql() -> str:
        return """
            SELECT name, category, brand, price, in_stock, product_url,
                   image_url, provider, currency
            FROM (
              SELECT r.*, ROW_NUMBER() OVER (
                PARTITION BY product_url
                ORDER BY depth DESC, cp.rank ASC,
                         CASE WHEN price IS NULL THEN 1 ELSE 0 END,
                         CASE WHEN in_stock IS NULL THEN 1 ELSE 0 END,
                         name ASC, COALESCE(brand, '') ASC
              ) AS rn
              FROM raw_products r JOIN category_priority cp USING (category)
            ) ranked WHERE rn = 1
        """

    def rows(self, batch_size: int = 500):
        cursor = self.db.execute(self.dedup_sql() + " ORDER BY product_url")
        while rows := cursor.fetchmany(batch_size):
            yield from rows

    def category_counts(self) -> list[tuple[str, int]]:
        return self.db.execute(
            "SELECT category, COUNT(*) FROM (" + self.dedup_sql() + ") GROUP BY category ORDER BY category"
        ).fetchall()

    def sample_by_category(self, count: int) -> list[tuple]:
        return self.db.execute("""
            SELECT name, category, brand, price, in_stock, product_url,
                   image_url, provider, currency
            FROM (
              SELECT d.*, ROW_NUMBER() OVER (PARTITION BY category ORDER BY product_url) AS sample_rank
              FROM (""" + self.dedup_sql() + """) d
            ) sampled
            WHERE sample_rank <= ?
            ORDER BY category, product_url
        """, [count]).fetchall()

    def close(self):
        self.db.close()
        self._tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
