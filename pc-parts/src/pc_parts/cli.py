from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from pc_parts.config import Settings
from pc_parts.database import LOCK_KEY, acquire_run_lock, synchronize
from pc_parts.normalization.categories import CANONICAL_CATEGORIES
from pc_parts.spiders import SPIDERS
from pc_parts.staging import Stage

LOG = logging.getLogger("pc_parts")


async def crawl_provider(provider: str, settings: Settings, args) -> bool:
    spider = SPIDERS[provider](
        limit_pages=args.limit_pages, limit_categories=args.limit_categories,
        categories=set(args.category) if args.category else None,
        delay=settings.crawl_delay_seconds,
    )
    limited = bool(args.limit_pages or args.limit_categories or args.category or args.sample_per_category)
    with Stage(provider, spider.base_url) as stage:
        try:
            async for item in spider.stream():
                stage.add(item)
            count = stage.finish()
            LOG.info("%s: raw=%s accepted=%s unique=%s invalid=%s pages=%s",
                     provider, spider.raw_count, stage.accepted_count, count,
                     stage.invalid_count, len(spider.visited_pages))
            for error in stage.invalid_examples:
                LOG.warning("%s invalid item: %s", provider, error)
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
                    "errors": spider.errors,
                    "database_changed": False,
                }, default=str, ensure_ascii=False))
            if limited or args.dry_run:
                if args.limit_pages is None:
                    spider.validate_complete()
                LOG.info("%s: preview only; PostgreSQL products unchanged", provider)
                return not spider.errors
            spider.validate_complete()
            if count < settings.min_products_per_provider:
                raise RuntimeError(f"only {count} unique products; minimum is {settings.min_products_per_provider}")
            result = synchronize(settings.database_url, provider, stage,
                                 max_delete_fraction=settings.max_delete_fraction)
            LOG.info("%s committed: %s", provider, json.dumps(result))
            return True
        except Exception:
            LOG.exception("%s failed; no replacement committed", provider)
            return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-run PC parts crawler")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="crawl once and exit")
    run.add_argument("--provider", choices=["all", *SPIDERS], default="all")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--limit-pages", type=int, metavar="N")
    run.add_argument("--limit-categories", type=int, metavar="N")
    run.add_argument("--category", action="append", choices=CANONICAL_CATEGORIES,
                     help="select canonical category; repeatable, preview only")
    run.add_argument("--sample-per-category", type=int, default=0, metavar="N",
                     help="print N normalized products per category; preview only")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    if args.limit_pages is not None and args.limit_pages < 1:
        parser.error("--limit-pages must be positive")
    if args.limit_categories is not None and args.limit_categories < 1:
        parser.error("--limit-categories must be positive")
    if args.sample_per_category < 0:
        parser.error("--sample-per-category cannot be negative")
    limited = bool(args.limit_pages or args.limit_categories or args.category or args.sample_per_category)
    if not (limited or args.dry_run) and not settings.database_url:
        parser.error("DATABASE_URL is required for authoritative runs")
    providers = list(SPIDERS) if args.provider == "all" else [args.provider]
    lock = None
    try:
        if not (limited or args.dry_run):
            lock = acquire_run_lock(settings.database_url)
        results = [asyncio.run(crawl_provider(provider, settings, args)) for provider in providers]
        return 0 if all(results) else 1
    except Exception:
        LOG.exception("job failed before provider crawl")
        return 1
    finally:
        if lock:
            lock.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
