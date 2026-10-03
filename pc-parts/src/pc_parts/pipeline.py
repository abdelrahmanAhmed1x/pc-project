"""One-command crawl, identity resolution, and Typesense refresh.

The Batch API can take hours. This command waits and can resume submitted jobs
without repeating a crawl. It never prints credentials or listing payloads.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg

from pc_parts.cli import main as crawl_main
from pc_parts.config import Settings
from pc_parts.database import LOCK_KEY
from pc_parts.resolution import BudgetLimitReached, apply, collect, prepare, submit

LOG = logging.getLogger("pc_parts.pipeline")
PIPELINE_LOCK_KEY = LOCK_KEY + 1
MAX_WAIT_SECONDS = 26 * 60 * 60


def _wait_for_batch(conn, batch_id: str, poll_seconds: int) -> dict:
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    previous_status = None
    while True:
        result = collect(conn, batch_id)
        status = result["status"]
        if status != previous_status:
            LOG.info("identity batch %s: %s", batch_id, status)
            previous_status = status
        if status == "completed":
            LOG.info("identity batch %s: accepted=%s unanswered=%s actual_usd=%s",
                     batch_id, result["accepted"], result["unanswered"], result["actual_usd"])
            if result["unanswered"]:
                LOG.warning("%s batch comparisons had no usable answer and remain separate",
                            result["unanswered"])
            return result
        if status in {"failed", "cancelled", "expired"}:
            raise RuntimeError(f"identity batch {batch_id} ended with status {status}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"identity batch {batch_id} is still {status}; rerun with --resume")
        conn.commit()
        time.sleep(poll_seconds)


def _apply_all(conn) -> int:
    total = 0
    while True:
        result = apply(conn, 1000)
        total += result["merged"]
        if result["merged"] < 1000:
            break
    LOG.info("identity: applied %s safe merges", total)
    return total


def _reindex(database_url: str) -> None:
    backend_dir = Path(__file__).resolve().parents[3] / "backend"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    LOG.info("reindexing Typesense from PostgreSQL")
    subprocess.run(["go", "run", "./cmd/reindex"], cwd=backend_dir,
                   env=environment, check=True)


def execute(settings: Settings, *, skip_crawl: bool = False, resume: bool = False,
            apply_existing: bool = False,
            batch_size: int = 1000, max_pairs: int | None = None,
            poll_seconds: int = 60) -> dict:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    if not apply_existing and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for the full pipeline; no crawl started")
    with psycopg.connect(settings.database_url, autocommit=True) as lock_conn:
        if not lock_conn.execute("SELECT pg_try_advisory_lock(%s)",
                                 (PIPELINE_LOCK_KEY,)).fetchone()[0]:
            raise RuntimeError("another full pipeline is already running")
        crawl_status = 0
        error = None
        result = {"crawl_status": 0, "luna_requests": 0, "merged": 0,
                  "budget_exhausted": False}
        try:
            if not skip_crawl and not resume and not apply_existing:
                LOG.info("starting full provider crawl")
                crawl_status = crawl_main(["run"], settings=settings)
                result["crawl_status"] = crawl_status
            if crawl_status:
                LOG.warning("some provider crawls failed; resolving committed offers and retaining failed-provider snapshots")
            with psycopg.connect(settings.database_url) as conn:
                    if not apply_existing:
                        pending = conn.execute("""
                            SELECT id FROM identity_batches WHERE status='submitted' ORDER BY created_at
                        """).fetchall()
                        for (batch_id,) in pending:
                            LOG.info("resuming submitted identity batch %s", batch_id)
                            _wait_for_batch(conn, batch_id, poll_seconds)
                    requested = 0
                    with tempfile.TemporaryDirectory(prefix="identity-batch-") as directory:
                        path = Path(directory) / "requests.jsonl"
                        while not apply_existing and (max_pairs is None or requested < max_pairs):
                            remaining = batch_size if max_pairs is None else min(batch_size, max_pairs - requested)
                            prepared = prepare(conn, path, remaining)
                            LOG.info("identity prepare: listings=%s deterministic=%s reused=%s luna=%s max_usd=%s budget_remaining_usd=%s",
                                     prepared["listings"], prepared["deterministic_decisions"],
                                     prepared["reused_decisions"], prepared["luna_requests"],
                                     prepared["reserved_max_usd"], prepared["budget_remaining_usd"])
                            if not prepared["luna_requests"]:
                                break
                            try:
                                submitted = submit(conn, path)
                            except BudgetLimitReached:
                                result["budget_exhausted"] = True
                                LOG.warning("$10 monthly identity budget reached; remaining pairs stay separate")
                                break
                            requested += submitted["requests"]
                            result["luna_requests"] += submitted["requests"]
                            LOG.info("submitted identity batch %s with %s requests", submitted["batch_id"],
                                     submitted["requests"])
                            _wait_for_batch(conn, submitted["batch_id"], poll_seconds)
                    result["merged"] = _apply_all(conn)
        except Exception as exc:
            error = exc
            LOG.exception("full pipeline interrupted before identity work completed")
        finally:
            # A provider can commit before another provider or Batch job fails.
            # Always refresh search from the catalog state that actually committed.
            try:
                _reindex(settings.database_url)
            except Exception as exc:
                LOG.exception("Typesense reindex failed")
                if error is None:
                    error = exc
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (PIPELINE_LOCK_KEY,))
        if error:
            raise error
        if crawl_status:
            raise RuntimeError("one or more provider crawls failed; committed offers were resolved and reindexed")
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crawl, resolve product identities, and reindex")
    parser.add_argument("--skip-crawl", action="store_true", help="test matching on the existing catalog")
    parser.add_argument("--resume", action="store_true", help="finish submitted batches without recrawling")
    parser.add_argument("--apply-existing", action="store_true",
                        help="apply collected decisions and reindex without crawling or submitting new model requests")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--max-pairs", type=int, help="limit model requests for a small test")
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.poll_seconds < 1 or (args.max_pairs is not None and args.max_pairs < 1):
        parser.error("batch-size, max-pairs, and poll-seconds must be positive")
    if args.resume and args.skip_crawl:
        parser.error("--resume already skips the crawl")
    if args.apply_existing and (args.resume or args.skip_crawl or args.max_pairs is not None):
        parser.error("--apply-existing already skips crawling and model submissions")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = execute(Settings.from_env(), skip_crawl=args.skip_crawl, resume=args.resume,
                         apply_existing=args.apply_existing,
                         batch_size=args.batch_size, max_pairs=args.max_pairs,
                         poll_seconds=args.poll_seconds)
    except Exception as exc:
        LOG.error("pipeline failed: %s", exc)
        return 1
    LOG.info("pipeline complete: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
