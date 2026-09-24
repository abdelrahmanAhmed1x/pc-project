import os
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest

from pc_parts.database import synchronize
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
        goose_sql = (Path(__file__).resolve().parents[1] / "init_schema.sql").read_text()
        up_sql = goose_sql.split("-- +goose Up", 1)[1].split("-- +goose Down", 1)[0]
        with psycopg.connect(url) as conn:
            conn.execute(up_sql)
        yield url
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def make_stage(provider: str, names: list[str]) -> Stage:
    base = {"sigma": "https://www.sigma-computer.com/en", "elnekhely": "https://www.elnekhelytechnology.com/"}[provider]
    stage = Stage(provider, base)
    for name in names:
        url = f"/en/item?id={name.lower()}" if provider == "sigma" else f"/{name.lower()}"
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
