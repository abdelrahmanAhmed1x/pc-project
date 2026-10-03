from __future__ import annotations

import logging

import psycopg
from psycopg.types.json import Jsonb

from pc_parts.staging import Stage
from pc_parts.catalog_stage import CatalogStage
from pc_parts.identity import Evidence, conflicts

LOCK_KEY = 7228541307
LOG = logging.getLogger("pc_parts.database")
PRICE_COVERAGE_MAX_ABSOLUTE_DROP = 0.20
PRICE_COVERAGE_MAX_RELATIVE_DROP = 0.30


def acquire_run_lock(database_url: str):
    conn = psycopg.connect(database_url, autocommit=True)
    locked = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]
    if not locked:
        conn.close()
        raise RuntimeError("another pc-parts run holds the PostgreSQL advisory lock")
    return conn


def synchronize(database_url: str, provider: str, stage: Stage, *, max_delete_fraction: float,
                catalog_stage: CatalogStage | None = None) -> dict:
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
                catalog_result = _synchronize_catalog(cur, provider, catalog_stage, max_delete_fraction) if catalog_stage else None
        result = {"staged": staged, "upserted": upserted, "deleted": deleted}
        if catalog_result:
            result["catalog"] = catalog_result
        return result


TRUST = {
    "sigma": "VERIFIED_DIRECT_RETAILER", "elnekhely": "VERIFIED_DIRECT_RETAILER",
    "elbadr": "VERIFIED_DIRECT_RETAILER", "compumarts": "VERIFIED_DIRECT_RETAILER",
    "alfrensia": "VERIFIED_DIRECT_RETAILER", "maximum": "VERIFIED_DIRECT_RETAILER",
    "dream2000": "VERIFIED_DIRECT_RETAILER", "tradeline": "VERIFIED_DIRECT_RETAILER",
    "twob": "VERIFIED_DIRECT_RETAILER", "switchplus": "VERIFIED_DIRECT_RETAILER",
    "raya": "VERIFIED_DIRECT_WITH_MARKETPLACE",
}


def begin_crawl_runs(database_url: str, providers: list[str]) -> dict[str, int]:
    """Persist the full requested provider set before concurrent crawls start."""
    runs = {}
    with psycopg.connect(database_url) as conn:
        for provider in providers:
            conn.execute("""
                INSERT INTO providers (name, trust_classification) VALUES (%s,%s)
                ON CONFLICT (name) DO NOTHING
            """, (provider, TRUST[provider]))
            provider_id = conn.execute("SELECT id FROM providers WHERE name=%s", (provider,)).fetchone()[0]
            abandoned = conn.execute("""
                UPDATE provider_crawl_runs SET status='failed', finished_at=now()
                WHERE provider_id=%s AND status='running'
            """, (provider_id,)).rowcount
            if abandoned:
                conn.execute("""
                    UPDATE providers SET last_crawl_status='failed', last_crawl_finished_at=now()
                    WHERE id=%s
                """, (provider_id,))
            runs[provider] = conn.execute("""
                INSERT INTO provider_crawl_runs (provider_id, status)
                VALUES (%s,'running') RETURNING id
            """, (provider_id,)).fetchone()[0]
    return runs


def finish_crawl_run(database_url: str, run_id: int, succeeded: bool) -> None:
    status = "succeeded" if succeeded else "failed"
    with psycopg.connect(database_url) as conn:
        row = conn.execute("""
            UPDATE provider_crawl_runs SET status=%s, finished_at=now()
            WHERE id=%s AND status='running' RETURNING provider_id
        """, (status, run_id)).fetchone()
        if not row:
            raise RuntimeError(f"crawl run {run_id} is no longer running")
        conn.execute("""
            UPDATE providers SET last_crawl_status=%s, last_crawl_finished_at=now()
            WHERE id=%s
        """, (status, row[0]))


def record_crawl_error(database_url: str, run_id: int, error: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute("""
            UPDATE provider_crawl_runs SET error_summary=%s
            WHERE id=%s AND status='running'
        """, (error[:2000], run_id))


def synchronize_catalog(database_url: str, provider: str, stage: CatalogStage,
                        *, max_delete_fraction: float) -> dict:
    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                return _synchronize_catalog(cur, provider, stage, max_delete_fraction)


def _refresh_isolated_source_identity(cur, variant_id: int, provider_id: int,
                                      item: dict, category_id: int, brand_id: int | None) -> bool:
    """Correct a retailer's own unmerged listing when its classification changes.

    A source identity is only a stable retailer listing ID, not proof that the
    earlier category or brand was correct. Never rewrite a shared or resolved
    canonical product this way.
    """
    owned = cur.execute("""
        SELECT v.product_id FROM product_variants v
        WHERE v.id=%s
          AND (SELECT count(*) FROM product_variants WHERE product_id=v.product_id)=1
          AND (SELECT count(*) FROM offers WHERE product_variant_id=v.id)=1
          AND EXISTS (SELECT 1 FROM offers WHERE product_variant_id=v.id
                      AND provider_id=%s AND source_key=%s)
          AND NOT EXISTS (SELECT 1 FROM variant_identity_aliases WHERE variant_id=v.id)
    """, (variant_id, provider_id, item["source_key"])).fetchone()
    if not owned:
        return False
    cur.execute("""
        UPDATE catalog_products
        SET category_id=%s, brand_id=%s, canonical_name=%s,
            model_number=%s, specifications=%s
        WHERE id=%s
    """, (category_id, brand_id, item["name"], item.get("model_number"),
          Jsonb(item.get("specifications") or {}), owned[0]))
    replacement_key = cur.execute("""
        SELECT id FROM product_variants WHERE identity_key=%s AND id<>%s
    """, (item["identity_key"], variant_id)).fetchone()
    current_key = cur.execute("SELECT identity_key FROM product_variants WHERE id=%s",
                              (variant_id,)).fetchone()[0]
    cur.execute("""
        UPDATE product_variants
        SET identity_key=%s, configuration=%s, manufacturer_part_number=%s, gtin=%s
        WHERE id=%s
    """, (current_key if replacement_key else item["identity_key"],
          Jsonb(item.get("variant") or {}), item.get("manufacturer_part_number"),
          item.get("gtin"), variant_id))
    return True


def _variant_evidence(cur, variant_id: int) -> Evidence:
    row = cur.execute("""
        SELECT c.slug, b.name, COALESCE(o.raw_name,p.canonical_name),
               v.manufacturer_part_number,v.gtin,p.model_number,
               v.configuration,p.specifications
        FROM product_variants v
        JOIN catalog_products p ON p.id=v.product_id
        JOIN categories c ON c.id=p.category_id
        LEFT JOIN brands b ON b.id=p.brand_id
        LEFT JOIN LATERAL (SELECT raw_name FROM offers WHERE product_variant_id=v.id
                           ORDER BY id LIMIT 1) o ON TRUE
        WHERE v.id=%s
    """, (variant_id,)).fetchone()
    return Evidence(*row)


def _identifier_candidate(cur, item: dict, incoming: Evidence) -> int | None:
    """An identifier narrows candidates; compatible evidence proves the match."""
    gtin = item.get("gtin")
    mpn = item.get("manufacturer_part_number")
    if not gtin and not mpn:
        return None
    candidates = cur.execute("""
        SELECT v.id FROM product_variants v
        JOIN catalog_products p ON p.id=v.product_id
        LEFT JOIN brands b ON b.id=p.brand_id
        WHERE (NULLIF(%s,'') IS NOT NULL AND v.gtin=%s)
           OR (NULLIF(%s,'') IS NOT NULL AND lower(v.manufacturer_part_number)=lower(%s)
               AND lower(b.name)=lower(%s))
        ORDER BY v.id
    """, (gtin, gtin, mpn, mpn, item.get("brand"))).fetchall()
    compatible = [row[0] for row in candidates
                  if not conflicts(_variant_evidence(cur, row[0]), incoming)]
    # A reused or malformed identifier must never choose arbitrarily.
    return compatible[0] if len(compatible) == 1 else None


def _synchronize_catalog(cur, provider: str, stage: CatalogStage,
                         max_delete_fraction: float) -> dict:
    if provider not in TRUST:
        raise RuntimeError(f"unverified provider: {provider}")
    staged_keys = set()
    staged_urls = set()
    count = 0
    known_prices = 0
    for item in stage.rows():
        staged_keys.add(item["source_key"])
        staged_urls.add(item["product_url"])
        count += 1
        known_prices += item["price_status"] == "known"
    if not count:
        raise RuntimeError("empty catalog offer stage; replacement refused")
    cur.execute("""
        INSERT INTO providers (name, trust_classification) VALUES (%s, %s)
        ON CONFLICT (name) DO NOTHING
    """, (provider, TRUST[provider]))
    provider_id, trust, approved_sellers = cur.execute(
        "SELECT id, trust_classification, approved_seller_ids FROM providers WHERE name=%s", (provider,)
    ).fetchone()
    if trust not in {"VERIFIED_DIRECT_RETAILER", "VERIFIED_DIRECT_WITH_MARKETPLACE"}:
        raise RuntimeError("provider is not approved for automatic ingestion")
    if trust == "VERIFIED_DIRECT_WITH_MARKETPLACE":
        if not approved_sellers or any(item.get("seller_id") not in approved_sellers for item in stage.rows()):
            raise RuntimeError("marketplace offer lacks an approved first-party seller ID")

    prior = cur.execute("SELECT source_key, url FROM offers WHERE provider_id=%s", (provider_id,)).fetchall()
    previous_known_prices = cur.execute("""
        SELECT count(*) FROM offers WHERE provider_id=%s AND price_status='known'
    """, (provider_id,)).fetchone()[0]
    previous_coverage = previous_known_prices / len(prior) if prior else None
    current_coverage = known_prices / count
    if (len(prior) >= 100 and count >= 100 and previous_coverage is not None
            and previous_coverage > 0.5
            and previous_coverage - current_coverage > PRICE_COVERAGE_MAX_ABSOLUTE_DROP
            and current_coverage < previous_coverage * (1 - PRICE_COVERAGE_MAX_RELATIVE_DROP)):
        raise RuntimeError(f"{provider}: price coverage fell from {previous_coverage:.1%} to "
                           f"{current_coverage:.1%}; replacement refused for price audit")
    to_delete = [(key, url) for key, url in prior if key not in staged_keys]
    # The migration's URL-only backfill keys are replaced by variant keys on
    # first crawl. Every later missing variant counts toward the guard.
    true_missing = [(key, url) for key, url in to_delete if not (key == url and url in staged_urls)]
    if prior and len(true_missing) / len(prior) > max_delete_fraction:
        raise RuntimeError(f"{provider}: catalog deletion guard blocked {len(true_missing)}/{len(prior)} removals")

    categories: dict[str, int] = {}
    brands: dict[str, int] = {}
    grouped_products: dict[tuple[str, str, str, str], int] = {}
    upserted = 0
    identity_conflicts = 0
    for item in stage.rows():
        category = item["category"]
        if category not in categories:
            cur.execute("INSERT INTO categories (slug) VALUES (%s) ON CONFLICT (slug) DO NOTHING", (category,))
            categories[category] = cur.execute("SELECT id FROM categories WHERE slug=%s", (category,)).fetchone()[0]
        brand = item.get("brand")
        brand_id = None
        if brand:
            if brand not in brands:
                cur.execute("INSERT INTO brands (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (brand,))
                brands[brand] = cur.execute("SELECT id FROM brands WHERE name=%s", (brand,)).fetchone()[0]
            brand_id = brands[brand]
        incoming = Evidence(category, brand, item["name"],
                            item.get("manufacturer_part_number"), item.get("gtin"),
                            item.get("model_number"), item.get("variant"),
                            item.get("specifications"))
        family = (incoming.attrs.get("generation") if category == "mobile_phones"
                  else incoming.attrs.get("cpu_model") if category == "cpu" else None)
        # A retailer parent ID is a catalog grouping hint, not proof that two
        # GPU boards, RAM kits, or laptop configurations are the same product.
        group = (str(item.get("provider_product_id") or item["product_url"])
                 if family else item["source_key"], category,
                 (brand or "").casefold(), family or "")
        # An existing offer owns its source identity even when an MPN or the
        # classification changed. The manufacturer identifier is only a
        # candidate for new offers, never the primary lookup key.
        source = cur.execute("""
            SELECT product_variant_id FROM offers WHERE provider_id=%s AND source_key=%s
        """, (provider_id, item["source_key"])).fetchone()
        variant_id = source[0] if source else None
        if variant_id is None:
            found = cur.execute("""
                SELECT id FROM product_variants WHERE identity_key=%s
                UNION ALL
                SELECT variant_id FROM variant_identity_aliases WHERE identity_key=%s
                LIMIT 1
            """, (item["identity_key"], item["identity_key"])).fetchone()
            variant_id = found[0] if found else _identifier_candidate(cur, item, incoming)
        if variant_id is not None:
            hard_conflicts = conflicts(_variant_evidence(cur, variant_id), incoming)
            if hard_conflicts:
                if source and _refresh_isolated_source_identity(cur, variant_id, provider_id, item,
                                                                categories[category], brand_id):
                    hard_conflicts = []
                else:
                    # A shared product or an identifier collision stays separate.
                    # Preserve the old shared variant and move only this offer.
                    identity_conflicts += 1
                    cur.execute("DELETE FROM variant_identity_aliases WHERE identity_key=%s AND variant_id=%s",
                                (item["identity_key"], variant_id))
                    if cur.execute("SELECT 1 FROM product_variants WHERE identity_key=%s",
                                   (item["identity_key"],)).fetchone():
                        item["identity_key"] += f":split:{variant_id}"
                    LOG.warning("%s identity conflict for %s: %s; creating separate source identity",
                                provider, item["product_url"], ",".join(hard_conflicts))
                    variant_id = None
        if variant_id is None:
            product_id = grouped_products.get(group)
            if product_id is None:
                product_id = cur.execute("""
                    INSERT INTO catalog_products (category_id, brand_id, canonical_name, model_number, specifications)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, (categories[category], brand_id, item["name"], item.get("model_number"),
                      Jsonb(item.get("specifications") or {}))).fetchone()[0]
                grouped_products[group] = product_id
            variant_id = cur.execute("""
                INSERT INTO product_variants (product_id, identity_key, configuration,
                                              manufacturer_part_number, gtin)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (product_id, item["identity_key"], Jsonb(item.get("variant") or {}),
                  item.get("manufacturer_part_number"), item.get("gtin"))).fetchone()[0]
        else:
            product_id = cur.execute("SELECT product_id FROM product_variants WHERE id=%s",
                                     (variant_id,)).fetchone()[0]
            grouped_products.setdefault(group, product_id)
        old_price = item.get("old_price")
        if old_price is not None and float(old_price) <= 0:
            old_price = None
        cur.execute("""
            INSERT INTO offers (product_variant_id, provider_id, source_key, provider_product_id,
                provider_variant_id, seller_id, sku, price, old_price, price_status,
                raw_price_text, currency, in_stock, condition, warranty, url, image_url, raw_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider_id, source_key) DO UPDATE SET
                product_variant_id=EXCLUDED.product_variant_id,
                provider_product_id=EXCLUDED.provider_product_id,
                provider_variant_id=EXCLUDED.provider_variant_id,
                seller_id=EXCLUDED.seller_id, sku=EXCLUDED.sku,
                price=EXCLUDED.price, old_price=EXCLUDED.old_price,
                price_status=EXCLUDED.price_status, raw_price_text=EXCLUDED.raw_price_text,
                currency=EXCLUDED.currency, in_stock=EXCLUDED.in_stock,
                condition=EXCLUDED.condition, warranty=EXCLUDED.warranty,
                url=EXCLUDED.url, image_url=EXCLUDED.image_url,
                raw_name=EXCLUDED.raw_name,
                last_seen_at=now(), price_checked_at=now(), updated_at=now()
        """, (variant_id, provider_id, item["source_key"], item.get("provider_product_id"),
              item.get("provider_variant_id"), item.get("seller_id"), item.get("sku"),
              item.get("price"), old_price, item["price_status"], item.get("raw_price_text"),
              item["currency"], item.get("in_stock"), item["condition"], item.get("warranty"),
              item["product_url"], item.get("image_url"), item["name"]))
        upserted += 1
    if to_delete:
        cur.execute("DELETE FROM offers WHERE provider_id=%s AND source_key = ANY(%s)",
                    (provider_id, [key for key, _ in to_delete]))
    cur.execute("DELETE FROM product_variants v WHERE NOT EXISTS (SELECT 1 FROM offers o WHERE o.product_variant_id=v.id)")
    cur.execute("DELETE FROM catalog_products p WHERE NOT EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id)")
    return {"staged": count, "upserted": upserted, "deleted": len(to_delete),
            "identity_conflicts": identity_conflicts, "known_prices": known_prices,
            "unknown_prices": count - known_prices,
            "previous_known_prices": previous_known_prices, "previous_offers": len(prior)}
