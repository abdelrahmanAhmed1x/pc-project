import json
import os
import time
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
import pc_parts.resolution as resolution

from pc_parts.database import (begin_crawl_runs, finish_crawl_run, record_crawl_error,
                               synchronize, synchronize_catalog)
from pc_parts.catalog_stage import CatalogStage
from pc_parts.identity import Evidence
from pc_parts.resolution import (apply as apply_resolution, budget_spent,
                                 Listing, prepare as prepare_resolution)
from pc_parts.staging import Stage


def isolated_url(base: str, schema: str) -> str:
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query))
    query["options"] = f"-csearch_path={schema}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


@pytest.fixture
def db_url():
    base = os.getenv("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL is not configured")
    schema = "test_pcparts_" + uuid.uuid4().hex[:12]
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    url = isolated_url(base, schema)
    try:
        migrations = Path(__file__).resolve().parents[2] / "backend" / "internal" / "migrations"
        with psycopg.connect(url) as conn:
            for migration in sorted(migrations.glob("*.sql")):
                goose_sql = migration.read_text()
                up_sql = goose_sql.split("-- +goose Up", 1)[1].split("-- +goose Down", 1)[0]
                conn.execute(up_sql)
        yield url
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def make_stage(provider: str, names: list[str]) -> Stage:
    base = {
        "sigma": "https://www.sigma-computer.com/en",
        "elnekhely": "https://www.elnekhelytechnology.com/",
        "maximum": "https://maximumhardware.store/",
        "alfrensia": "https://alfrensia.com/en/",
        "compumarts": "https://www.compumarts.com/",
    }[provider]
    stage = Stage(provider, base)
    for name in names:
        url = {
            "sigma": f"/en/item?id={name.lower()}",
            "alfrensia": f"/en/product/{name.lower()}",
            "compumarts": f"/products/{name.lower()}",
        }.get(provider, f"/{name.lower()}")
        stage.add({"name": name, "category": "cpu", "brand": "AMD",
                   "price": "100 EGP", "in_stock": True, "product_url": url})
    stage.finish()
    return stage


def rows(url):
    with psycopg.connect(url) as conn:
        return conn.execute("""
          SELECT v.name, p.name, p.created_at, p.updated_at
          FROM products p JOIN providers v ON v.id=p.provider_id
          ORDER BY v.name, p.name
        """).fetchall()


def named_row(conn, query):
    cursor = conn.execute(query)
    return dict(zip((column.name for column in cursor.description), cursor.fetchone()))


def test_idempotent_provider_deletion_and_rollback(db_url):
    with make_stage("sigma", ["One", "Two"]) as stage:
        assert synchronize(db_url, "sigma", stage, max_delete_fraction=1)["upserted"] == 2
    original = rows(db_url)
    with make_stage("sigma", ["One", "Two"]) as stage:
        assert synchronize(db_url, "sigma", stage, max_delete_fraction=1)["upserted"] == 0
    assert rows(db_url) == original

    time.sleep(0.01)
    with make_stage("sigma", ["One", "Two"]) as stage:
        stage.db.execute("UPDATE raw_products SET price=150 WHERE name='One'")
        assert synchronize(db_url, "sigma", stage, max_delete_fraction=1)["upserted"] == 1
    changed = rows(db_url)
    assert changed[0][2] == original[0][2]
    assert changed[0][3] > original[0][3]
    assert changed[1][3] == original[1][3]

    with make_stage("elnekhely", ["Other"]) as stage:
        synchronize(db_url, "elnekhely", stage, max_delete_fraction=1)
    with make_stage("sigma", ["One"]) as stage:
        result = synchronize(db_url, "sigma", stage, max_delete_fraction=1)
        assert result["deleted"] == 1
    assert [(provider, name) for provider, name, *_ in rows(db_url)] == [
        ("elnekhely", "Other"), ("sigma", "One")
    ]
    before_failure = rows(db_url)
    with make_stage("sigma", ["New"]) as stage:
        stage.db.execute("UPDATE raw_products SET currency='USD'")
        with pytest.raises(psycopg.errors.CheckViolation):
            synchronize(db_url, "sigma", stage, max_delete_fraction=1)
    assert rows(db_url) == before_failure


def test_delete_guard_preserves_provider(db_url):
    with make_stage("sigma", ["One", "Two"]) as stage:
        synchronize(db_url, "sigma", stage, max_delete_fraction=1)
    before = rows(db_url)
    with make_stage("sigma", ["One"]) as stage:
        with pytest.raises(RuntimeError, match="deletion guard"):
            synchronize(db_url, "sigma", stage, max_delete_fraction=0.35)
    assert rows(db_url) == before


def test_new_providers_use_same_upsert_contract(db_url):
    for provider in ("alfrensia", "maximum", "compumarts"):
        with make_stage(provider, ["One"]) as stage:
            assert synchronize(db_url, provider, stage, max_delete_fraction=1)["upserted"] == 1
        with make_stage(provider, ["One"]) as stage:
            assert synchronize(db_url, provider, stage, max_delete_fraction=1)["upserted"] == 0
    assert {provider for provider, *_ in rows(db_url)} == {"alfrensia", "maximum", "compumarts"}


def test_monitor_and_accessories_are_saved(db_url):
    with Stage("compumarts", "https://www.compumarts.com/") as stage:
        for category in ("monitor", "accessories"):
            stage.add({"name": category, "category": category,
                       "product_url": f"/products/{category}", "price": "100 EGP"})
        assert stage.finish() == 2
        assert synchronize(db_url, "compumarts", stage, max_delete_fraction=1)["staged"] == 2
    with psycopg.connect(db_url) as conn:
        assert conn.execute("""
            SELECT c.slug FROM products p JOIN categories c ON c.id=p.category_id ORDER BY c.slug
        """).fetchall() == [("accessories",), ("monitor",)]


def test_catalog_variants_prices_and_trust(db_url):
    with CatalogStage("dream2000", "https://dream2000.com/") as stage:
        for variant_id, storage, price in (("11", "256GB", "0"), ("12", "512GB", "59999")):
            stage.add({"name": "Apple iPhone 17 Pro", "category": "mobile_phones", "brand": "Apple",
                       "provider_product_id": "10", "provider_variant_id": variant_id,
                       "variant": {"Storage": storage}, "price": price,
                       "product_url": "/products/example-phone", "in_stock": True})
        assert stage.finish() == 2
        synchronize_catalog(db_url, "dream2000", stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM catalog_products").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM product_variants").fetchone()[0] == 2
        assert conn.execute("SELECT price, price_status FROM offers ORDER BY provider_variant_id").fetchall() == [
            (None, "placeholder"), (59999, "known")]
        conn.execute("UPDATE providers SET trust_classification='UNVERIFIED' WHERE name='dream2000'")
        conn.commit()
    with CatalogStage("dream2000", "https://dream2000.com/") as stage:
        stage.add({"name": "Apple iPhone 17 Pro", "category": "mobile_phones", "brand": "Apple",
                   "provider_product_id": "10", "provider_variant_id": "11",
                   "price": "0", "product_url": "/products/example-phone"})
        stage.finish()
        with pytest.raises(RuntimeError, match="not approved"):
            synchronize_catalog(db_url, "dream2000", stage, max_delete_fraction=1)


def test_retailer_parent_id_does_not_group_different_gpu_boards(db_url):
    with CatalogStage("dream2000", "https://dream2000.com/") as stage:
        for variant_id, board in (("11", "Eagle"), ("12", "Windforce")):
            stage.add({"name": f"Gigabyte RTX 3050 {board} OC 6G", "category": "gpu",
                       "brand": "Gigabyte", "provider_product_id": "shared-parent",
                       "provider_variant_id": variant_id, "variant": {"Board": board},
                       "price": "10000", "product_url": "/products/rtx-3050"})
        stage.finish()
        synchronize_catalog(db_url, "dream2000", stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM catalog_products").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM product_variants").fetchone()[0] == 2


def test_price_coverage_regression_rolls_back_provider_replacement(db_url):
    def stage_with_prices(known: int):
        stage = CatalogStage("dream2000", "https://dream2000.com/")
        for i in range(100):
            stage.add({"name": f"Example headphones {i}", "category": "headphones",
                       "brand": "Example", "price": "550" if i < known else None,
                       "product_url": f"/products/headphones-{i}"})
        stage.finish()
        return stage

    with stage_with_prices(100) as stage:
        synchronize_catalog(db_url, "dream2000", stage, max_delete_fraction=1)
    with stage_with_prices(30) as stage:
        with pytest.raises(RuntimeError, match="price coverage fell"):
            synchronize_catalog(db_url, "dream2000", stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM offers WHERE price_status='known'").fetchone()[0] == 100


def test_budget_uses_measured_completed_cost_with_margin(db_url):
    with psycopg.connect(db_url) as conn:
        for status, actual in (("completed", Decimal("0.05")), ("submitted", None),
                               ("failed", None), ("completed", None)):
            conn.execute("""
                INSERT INTO identity_batches (id,input_sha256,reserved_usd,actual_usd,status)
                VALUES (%s,%s,1,%s,%s)
            """, (uuid.uuid4().hex, uuid.uuid4().hex, actual, status))
        assert budget_spent(conn) == Decimal("3.10")


def test_prepare_prioritizes_stronger_paid_candidates(db_url, tmp_path, monkeypatch):
    def item(variant_id, provider_id, title):
        return Listing(variant_id, variant_id, provider_id, str(variant_id),
                       Evidence("headphones", "JBL", title))

    weak = (item(1, 1, "JBL 530BT headphones"), item(2, 2, "JBL Tune 530BT earbuds"), 0.5)
    strong = (item(3, 1, "JBL Tune 770NC Black"), item(4, 2, "JBL Tune 770NC Black"), 1.0)
    monkeypatch.setattr(resolution, "load_listings", lambda _conn: [*weak[:2], *strong[:2]])
    monkeypatch.setattr(resolution, "candidates", lambda _listings: iter((weak, strong)))
    path = tmp_path / "identity.jsonl"
    with psycopg.connect(db_url) as conn:
        assert prepare_resolution(conn, path, 1)["luna_requests"] == 1
    assert path.read_text().count("\n") == 1
    assert json.loads(path.read_text())["custom_id"].startswith("3:4|")


def test_exact_part_number_reuses_variant_across_retailers(db_url):
    for provider, base, product_id, variant_id in (
        ("dream2000", "https://dream2000.com/", "5", "51"),
        ("tradeline", "https://tradelinestores.com/", "8", "81"),
    ):
        with CatalogStage(provider, base) as stage:
            stage.add({"name": "Apple iPhone Example 256GB Black", "category": "mobile_phones",
                       "brand": "Apple", "manufacturer_part_number": "AB123AF/A",
                       "provider_product_id": product_id, "provider_variant_id": variant_id,
                       "price": "40000", "in_stock": True,
                       "product_url": "/products/iphone-example"})
            stage.finish()
            synchronize_catalog(db_url, provider, stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM catalog_products").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM product_variants").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM offers").fetchone()[0] == 2


def test_isolated_source_listing_can_be_reclassified(db_url):
    base = "https://www.sigma-computer.com/en"
    url = "/en/item?id=fantech-alto-mh91"
    with CatalogStage("sigma", base) as stage:
        stage.add({"name": "Fantech Alto MH91", "category": "accessories",
                   "brand": "Fantech", "product_url": url, "price": "1000"})
        stage.finish()
        synchronize_catalog(db_url, "sigma", stage, max_delete_fraction=1)
    with CatalogStage("sigma", base) as stage:
        stage.add({"name": "Fantech Alto MH91 gaming headset", "category": "headsets",
                   "brand": "Fantech", "product_url": url, "price": "1100"})
        stage.finish()
        synchronize_catalog(db_url, "sigma", stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        assert conn.execute("""
            SELECT c.slug, p.canonical_name, o.price FROM offers o
            JOIN product_variants v ON v.id=o.product_variant_id
            JOIN catalog_products p ON p.id=v.product_id
            JOIN categories c ON c.id=p.category_id
        """).fetchall() == [("headsets", "Fantech Alto MH91 gaming headset", 1100)]
        assert conn.execute("SELECT count(*) FROM catalog_products").fetchone()[0] == 1


def test_same_source_with_mpn_can_be_reclassified(db_url):
    base = "https://2b.com.eg/en/"
    url = "/en/logitech-h340.html"
    with CatalogStage("twob", base) as stage:
        stage.add({"name": "Logitech H340", "category": "headphones", "brand": "Logitech",
                   "manufacturer_part_number": "981-000475", "product_url": url, "price": "1000"})
        stage.finish()
        synchronize_catalog(db_url, "twob", stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE product_variants SET identity_key='mpn:logitech:981-000475'")
    with CatalogStage("twob", base) as stage:
        stage.add({"name": "Logitech USB Headset H340", "category": "headsets", "brand": "Logitech",
                   "manufacturer_part_number": "981-000475", "product_url": url, "price": "1100"})
        stage.finish()
        assert synchronize_catalog(db_url, "twob", stage, max_delete_fraction=1)["identity_conflicts"] == 0
    with psycopg.connect(db_url) as conn:
        assert conn.execute("""
            SELECT c.slug, o.price, v.identity_key FROM offers o
            JOIN product_variants v ON v.id=o.product_variant_id
            JOIN catalog_products p ON p.id=v.product_id
            JOIN categories c ON c.id=p.category_id
        """).fetchall() == [("headsets", 1100, "source:twob:https://2b.com.eg/en/logitech-h340.html:{}")]


def test_reused_mpn_does_not_force_different_products_together(db_url):
    base = "https://2b.com.eg/en/"
    with CatalogStage("twob", base) as stage:
        for name, category, url in (
            ("Logitech H340", "headphones", "/en/logitech-h340.html"),
            ("Logitech USB Headset H340", "headsets", "/en/logitech-h340-headset.html"),
        ):
            stage.add({"name": name, "category": category, "brand": "Logitech",
                       "manufacturer_part_number": "981-000475", "product_url": url, "price": "1000"})
        stage.finish()
        synchronize_catalog(db_url, "twob", stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM catalog_products").fetchone()[0] == 2


def test_shared_source_identity_is_split_without_changing_other_offer(db_url):
    base = "https://www.sigma-computer.com/en"
    url = "/en/item?id=fantech-alto-mh91"
    with CatalogStage("sigma", base) as stage:
        stage.add({"name": "Fantech Alto MH91", "category": "accessories",
                   "brand": "Fantech", "manufacturer_part_number": "MH91",
                   "product_url": url, "price": "1000"})
        stage.finish()
        synchronize_catalog(db_url, "sigma", stage, max_delete_fraction=1)
    with CatalogStage("dream2000", "https://dream2000.com/") as stage:
        stage.add({"name": "Fantech Alto MH91", "category": "accessories",
                   "brand": "Fantech", "manufacturer_part_number": "MH91",
                   "product_url": "/products/fantech-alto-mh91", "price": "1200"})
        stage.finish()
        synchronize_catalog(db_url, "dream2000", stage, max_delete_fraction=1)
    with CatalogStage("sigma", base) as stage:
        stage.add({"name": "Fantech Alto MH91 gaming headset", "category": "headsets",
                   "brand": "Fantech", "manufacturer_part_number": "MH91",
                   "product_url": url, "price": "1100"})
        stage.finish()
        result = synchronize_catalog(db_url, "sigma", stage, max_delete_fraction=1)
        assert result["identity_conflicts"] == 1
    with psycopg.connect(db_url) as conn:
        assert conn.execute("""
            SELECT pr.name, c.slug, o.price FROM offers o
            JOIN providers pr ON pr.id=o.provider_id
            JOIN product_variants v ON v.id=o.product_variant_id
            JOIN catalog_products p ON p.id=v.product_id
            JOIN categories c ON c.id=p.category_id
            ORDER BY pr.name
        """).fetchall() == [("dream2000", "accessories", 1200),
                            ("sigma", "headsets", 1100)]


def test_index_keeps_a_real_price_when_retailer_is_sold_out(db_url):
    with CatalogStage("dream2000", "https://dream2000.com/") as stage:
        stage.add({"name": "Sold-out headphones", "category": "headphones", "brand": "Example",
                   "provider_product_id": "100", "provider_variant_id": "101", "price": "550",
                   "in_stock": False, "product_url": "/products/sold-out-headphones"})
        stage.finish()
        synchronize_catalog(db_url, "dream2000", stage, max_delete_fraction=1)
    sql = (Path(__file__).resolve().parents[2] / "backend" / "internal" / "modules" /
           "products" / "internal" / "queries" / "queries.sql").read_text()
    query = sql.split("-- name: GetProductsForIndexing :many", 1)[1].split(
        "-- name: GetOffersForProduct :many", 1)[0]
    query = query.replace("sqlc.arg('after_id')", "0").replace("sqlc.arg('batch_size')", "100")
    with psycopg.connect(db_url) as conn:
        row = named_row(conn, query)
    assert row["price"] == 550
    assert row["price_status"] == "known"
    assert row["in_stock"] is False


def test_failed_provider_price_is_not_presented_as_current(db_url):
    with CatalogStage("dream2000", "https://dream2000.com/") as stage:
        stage.add({"name": "Example headphones", "category": "headphones", "brand": "Example",
                   "price": "550", "in_stock": True,
                   "product_url": "/products/example-headphones"})
        stage.finish()
        synchronize_catalog(db_url, "dream2000", stage, max_delete_fraction=1)
    sql = (Path(__file__).resolve().parents[2] / "backend" / "internal" / "modules" /
           "products" / "internal" / "queries" / "queries.sql").read_text()
    query = sql.split("-- name: GetProductsForIndexing :many", 1)[1].split(
        "-- name: GetOffersForProduct :many", 1)[0]
    query = query.replace("sqlc.arg('after_id')", "0").replace("sqlc.arg('batch_size')", "100")
    run_id = begin_crawl_runs(db_url, ["dream2000"])["dream2000"]
    record_crawl_error(db_url, run_id, "pagination repeated after retry")
    finish_crawl_run(db_url, run_id, False)
    with psycopg.connect(db_url) as conn:
        row = named_row(conn, query)
        assert row["price"] is None and row["price_status"] == "stale"
        assert row["last_seen_price"] == 550 and row["last_seen_at"] is not None
        assert row["offer_count"] == 0
        offers_query = sql.split("-- name: GetOffersForProduct :many", 1)[1]
        offers_query = offers_query.replace("sqlc.arg('product_id')", str(row["id"]))
        assert named_row(conn, offers_query)["is_current"] is False
        assert conn.execute("SELECT price FROM offers").fetchone()[0] == 550
        assert conn.execute("SELECT status, error_summary FROM provider_crawl_runs WHERE id=%s",
                            (run_id,)).fetchone() == ("failed", "pagination repeated after retry")
    run_id = begin_crawl_runs(db_url, ["dream2000"])["dream2000"]
    finish_crawl_run(db_url, run_id, True)
    with psycopg.connect(db_url) as conn:
        assert named_row(conn, query)["price"] == 550


def test_current_retailer_wins_over_failed_cheaper_retailer(db_url):
    for provider, base, price in (
        ("dream2000", "https://dream2000.com/", "550"),
        ("tradeline", "https://tradelinestores.com/", "700"),
    ):
        with CatalogStage(provider, base) as stage:
            stage.add({"name": "Example headphones", "category": "headphones", "brand": "Example",
                       "manufacturer_part_number": "HX-123", "price": price, "in_stock": True,
                       "product_url": "/products/example-headphones"})
            stage.finish()
            synchronize_catalog(db_url, provider, stage, max_delete_fraction=1)
    run_id = begin_crawl_runs(db_url, ["dream2000"])["dream2000"]
    finish_crawl_run(db_url, run_id, False)
    sql = (Path(__file__).resolve().parents[2] / "backend" / "internal" / "modules" /
           "products" / "internal" / "queries" / "queries.sql").read_text()
    query = sql.split("-- name: GetProductsForIndexing :many", 1)[1].split(
        "-- name: GetOffersForProduct :many", 1)[0]
    query = query.replace("sqlc.arg('after_id')", "0").replace("sqlc.arg('batch_size')", "100")
    with psycopg.connect(db_url) as conn:
        row = named_row(conn, query)
        assert row["price"] == 700 and row["provider_name"] == "tradeline" and row["offer_count"] == 1


def test_resolved_exact_variant_survives_next_provider_crawl(db_url, tmp_path):
    cases = (("dream2000", "https://dream2000.com/", "AMD Ryzen 7 7800X3D Box"),
             ("tradeline", "https://tradelinestores.com/", "Ryzen 7 7800X3D Box Processor"))
    for provider, base, name in cases:
        with CatalogStage(provider, base) as stage:
            stage.add({"name": name, "category": "cpu", "brand": "AMD",
                       "provider_product_id": provider, "price": "10000",
                       "product_url": f"/products/{provider}-cpu"})
            stage.finish()
            synchronize_catalog(db_url, provider, stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        prepared = prepare_resolution(conn, tmp_path / "identity.jsonl", 20)
        assert prepared["deterministic_decisions"] == 1
        assert apply_resolution(conn, 20)["merged"] == 1
        assert conn.execute("SELECT count(*) FROM catalog_products").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM offers").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM variant_identity_aliases").fetchone()[0] == 1
    provider, base, name = cases[1]
    with CatalogStage(provider, base) as stage:
        stage.add({"name": name, "category": "cpu", "brand": "AMD",
                   "provider_product_id": provider, "price": "9500",
                   "product_url": f"/products/{provider}-cpu"})
        stage.finish()
        synchronize_catalog(db_url, provider, stage, max_delete_fraction=1)
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM catalog_products").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM product_variants").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM offers").fetchone()[0] == 2
