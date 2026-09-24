from __future__ import annotations

import psycopg

from pc_parts.staging import Stage

LOCK_KEY = 7228541307


def acquire_run_lock(database_url: str):
    conn = psycopg.connect(database_url, autocommit=True)
    locked = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]
    if not locked:
        conn.close()
        raise RuntimeError("another pc-parts run holds the PostgreSQL advisory lock")
    return conn


def synchronize(database_url: str, provider: str, stage: Stage, *, max_delete_fraction: float) -> dict:
    """Replace one provider atomically; a raised exception rolls back every mutation."""
    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TEMP TABLE stage_products (
                      name TEXT NOT NULL, category TEXT NOT NULL, brand TEXT,
                      price NUMERIC(12,2), in_stock BOOLEAN,
                      canonical_product_url TEXT NOT NULL PRIMARY KEY,
                      image_url TEXT, currency CHAR(3) NOT NULL
                    ) ON COMMIT DROP
                """)
                with cur.copy("COPY stage_products (name, category, brand, price, in_stock, canonical_product_url, image_url, currency) FROM STDIN") as copy:
                    for name, category, brand, price, stock, url, image, _provider, currency in stage.rows():
                        copy.write_row((name, category, brand, price, stock, url, image, currency))

                staged = cur.execute("SELECT count(*) FROM stage_products").fetchone()[0]
                if staged == 0:
                    raise RuntimeError("empty provider stage; replacement refused")
                existing = cur.execute("""
                    SELECT count(*) FROM products p JOIN providers v ON v.id=p.provider_id WHERE v.name=%s
                """, (provider,)).fetchone()[0]
                to_delete = cur.execute("""
                    SELECT count(*) FROM products p JOIN providers v ON v.id=p.provider_id
                    WHERE v.name=%s AND NOT EXISTS (
                      SELECT 1 FROM stage_products s WHERE s.canonical_product_url=p.canonical_product_url
                    )
                """, (provider,)).fetchone()[0]
                if existing and to_delete / existing > max_delete_fraction:
                    raise RuntimeError(f"{provider}: deletion guard blocked {to_delete}/{existing} removals")

                cur.execute("INSERT INTO providers (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (provider,))
                cur.execute("INSERT INTO categories (slug) SELECT DISTINCT category FROM stage_products ON CONFLICT (slug) DO NOTHING")
                cur.execute("INSERT INTO brands (name) SELECT DISTINCT brand FROM stage_products WHERE brand IS NOT NULL ON CONFLICT (name) DO NOTHING")
                cur.execute("""
                    INSERT INTO products (
                      provider_id, category_id, brand_id, name, price, currency,
                      in_stock, canonical_product_url, image_url
                    )
                    SELECT v.id, c.id, b.id, s.name, s.price, s.currency,
                           s.in_stock, s.canonical_product_url, s.image_url
                    FROM stage_products s
                    JOIN providers v ON v.name=%s
                    JOIN categories c ON c.slug=s.category
                    LEFT JOIN brands b ON b.name=s.brand
                    ON CONFLICT (provider_id, canonical_product_url) DO UPDATE SET
                      category_id=EXCLUDED.category_id,
                      brand_id=EXCLUDED.brand_id,
                      name=EXCLUDED.name,
                      price=EXCLUDED.price,
                      currency=EXCLUDED.currency,
                      in_stock=EXCLUDED.in_stock,
                      image_url=EXCLUDED.image_url,
                      updated_at=now()
                    WHERE (products.category_id, products.brand_id, products.name, products.price,
                           products.currency, products.in_stock, products.image_url)
                      IS DISTINCT FROM
                          (EXCLUDED.category_id, EXCLUDED.brand_id, EXCLUDED.name, EXCLUDED.price,
                           EXCLUDED.currency, EXCLUDED.in_stock, EXCLUDED.image_url)
                """, (provider,))
                upserted = cur.rowcount
                cur.execute("""
                    DELETE FROM products p USING providers v
                    WHERE p.provider_id=v.id AND v.name=%s AND NOT EXISTS (
                      SELECT 1 FROM stage_products s WHERE s.canonical_product_url=p.canonical_product_url
                    )
                """, (provider,))
                deleted = cur.rowcount
        return {"staged": staged, "upserted": upserted, "deleted": deleted}
