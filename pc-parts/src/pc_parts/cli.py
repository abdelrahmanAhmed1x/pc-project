from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from pc_parts.config import Settings
from pc_parts.catalog_stage import CatalogStage
from pc_parts.database import (LOCK_KEY, acquire_run_lock, begin_crawl_runs,
                               finish_crawl_run, record_crawl_error,
                               synchronize, synchronize_catalog)
from pc_parts.normalization.categories import CANONICAL_CATEGORIES
from pc_parts.spiders import SPIDERS
from pc_parts.staging import Stage

LOG = logging.getLogger("pc_parts")
SYNC_LOCK = threading.Lock()


async def crawl_provider(provider: str, settings: Settings, args) -> bool:
    spider = SPIDERS[provider](
        limit_pages=args.limit_pages, limit_categories=args.limit_categories,
        categories=set(args.category) if args.category else None,
        delay=settings.crawl_delay_seconds,
    )
    limited = bool(args.limit_pages or args.limit_categories or args.category or args.sample_per_category)
    with Stage(provider, spider.base_url) as stage, CatalogStage(provider, spider.base_url) as catalog_stage:
        try:
            async for item in spider.stream():
                stage.add(item)
                catalog_stage.add(item)
            count = stage.finish()
            offer_count = catalog_stage.finish()
            LOG.info("%s: raw=%s accepted=%s unique=%s invalid=%s placeholder_prices=%s pages=%s",
                     provider, spider.raw_count, stage.accepted_count, count,
                     stage.invalid_count, stage.placeholder_count, len(spider.visited_pages))
            for error in stage.invalid_examples:
                LOG.warning("%s invalid item: %s", provider, error)
            for url in stage.placeholder_examples:
                LOG.warning("%s placeholder price stored as unknown: %s", provider, url)
            for error in catalog_stage.invalid_examples:
                LOG.warning("%s invalid catalog offer: %s", provider, error)
            for example in catalog_stage.unknown_price_examples:
                LOG.info("%s offer without a known price: %s", provider, example)
            if args.sample_per_category:
                columns = ("name", "category", "brand", "price", "in_stock", "product_url",
                           "image_url", "provider", "currency")
                category_counts = dict(stage.category_counts())
                discovered_categories = sorted({seed.category for seed in spider.discovered})
                print(json.dumps({
                    "provider": provider,
                    "discovered_categories": discovered_categories,
                    "category_counts": category_counts,
                    "empty_categories": sorted(set(discovered_categories) - set(category_counts)),
                    "samples": [dict(zip(columns, row)) for row in stage.sample_by_category(args.sample_per_category)],
                    "invalid_rows": stage.invalid_count,
                    "offer_count": offer_count,
                    "invalid_offers": catalog_stage.invalid_count,
                    "errors": spider.errors,
                    "database_changed": False,
                }, default=str, ensure_ascii=False))
            if limited or args.dry_run:
                if args.limit_pages is None:
                    spider.validate_complete()
                LOG.info("%s: preview only; PostgreSQL products unchanged", provider)
                return not spider.errors
            spider.validate_complete()
            if offer_count < settings.min_products_per_provider:
                raise RuntimeError(f"only {offer_count} unique offers; minimum is {settings.min_products_per_provider}")
            with SYNC_LOCK:
                if provider in {"dream2000", "tradeline", "twob", "switchplus"}:
                    result = synchronize_catalog(settings.database_url, provider, catalog_stage,
                                                 max_delete_fraction=settings.max_delete_fraction)
                else:
                    result = synchronize(settings.database_url, provider, stage,
                                         max_delete_fraction=settings.max_delete_fraction,
                                         catalog_stage=catalog_stage)
            LOG.info("%s committed: %s", provider, json.dumps(result))
            return True
        except Exception as exc:
            LOG.exception("%s failed; no replacement committed", provider)
            run_id = getattr(args, "run_ids", {}).get(provider)
            if run_id:
                try:
                    record_crawl_error(settings.database_url, run_id, str(exc))
                except Exception:
                    LOG.exception("%s failure reason could not be recorded", provider)
            return False


def run_provider(provider: str, settings: Settings, args) -> bool:
    # Each crawl has blocking staging and database work, so give it its own
    # thread and event loop instead of blocking the other spiders.
    return asyncio.run(crawl_provider(provider, settings, args))


def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-run PC parts crawler")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="crawl once and exit")
    run.add_argument("--provider", action="append", choices=["all", *SPIDERS],
                     help="provider to crawl; repeat to crawl a selected set concurrently (default: all except Switch Plus)")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--limit-pages", type=int, metavar="N")
    run.add_argument("--limit-categories", type=int, metavar="N")
    run.add_argument("--category", action="append", choices=CANONICAL_CATEGORIES,
                     help="select canonical category; repeatable, preview only")
    run.add_argument("--sample-per-category", type=int, default=0, metavar="N",
                     help="print N normalized products per category; preview only")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = settings or Settings.from_env()
    if args.limit_pages is not None and args.limit_pages < 1:
        parser.error("--limit-pages must be positive")
    if args.limit_categories is not None and args.limit_categories < 1:
        parser.error("--limit-categories must be positive")
    if args.sample_per_category < 0:
        parser.error("--sample-per-category cannot be negative")
    limited = bool(args.limit_pages or args.limit_categories or args.category or args.sample_per_category)
    if not (limited or args.dry_run) and not settings.database_url:
        parser.error("DATABASE_URL is required for authoritative runs")
    requested = args.provider or ["all"]
    if "all" in requested and len(requested) > 1:
        parser.error("--provider all cannot be combined with another provider")
    providers = ([name for name in SPIDERS if name != "switchplus"] if requested == ["all"]
                 else list(dict.fromkeys(requested)))
    lock = None
    try:
        if not (limited or args.dry_run):
            lock = acquire_run_lock(settings.database_url)
        runs = begin_crawl_runs(settings.database_url, providers) if lock else {}
        args.run_ids = runs
        outcomes: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(providers)) as executor:
            futures = {executor.submit(run_provider, provider, settings, args): provider
                       for provider in providers}
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    success = bool(future.result())
                except Exception as exc:
                    LOG.exception("%s failed before crawl completed", provider)
                    if provider in runs:
                        try:
                            record_crawl_error(settings.database_url, runs[provider], str(exc))
                        except Exception:
                            LOG.exception("%s failure reason could not be recorded", provider)
                    success = False
                outcomes[provider] = "succeeded" if success else "failed"
                if provider in runs:
                    try:
                        finish_crawl_run(settings.database_url, runs[provider], success)
                    except Exception:
                        LOG.exception("%s result could not be recorded", provider)
                        outcomes[provider] = "failed"
        LOG.info("crawl summary: %s", json.dumps({provider: outcomes[provider] for provider in providers}))
        return 0 if all(status == "succeeded" for status in outcomes.values()) else 1
    except Exception:
        LOG.exception("job failed before provider crawl")
        return 1
    finally:
        if lock:
            lock.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
