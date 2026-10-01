import asyncio
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from pc_parts import cli
from pc_parts.config import Settings
from pc_parts.models import CategorySeed


class FakeSpider:
    base_url = "https://www.sigma-computer.com/en"

    def __init__(self, **_):
        self.errors = []
        self.raw_count = 1
        self.visited_pages = {"page1"}
        self.discovered = [CategorySeed("https://www.sigma-computer.com/en/category/test", "cpu")]

    async def stream(self):
        yield {"name": "Part", "category": "cpu", "product_url": "/en/item?id=part"}

    def validate_complete(self):
        raise RuntimeError("missing required page")


def test_limited_and_failed_crawls_never_synchronize(monkeypatch):
    monkeypatch.setitem(cli.SPIDERS, "sigma", FakeSpider)
    called = []
    monkeypatch.setattr(cli, "synchronize", lambda *a, **k: called.append(True))
    settings = Settings("unused", "Africa/Cairo", 0, 1, 0.35)
    limited = SimpleNamespace(limit_pages=1, limit_categories=1, category=None,
                              sample_per_category=0, dry_run=False)
    assert asyncio.run(cli.crawl_provider("sigma", settings, limited)) is True
    assert called == []
    selected = SimpleNamespace(limit_pages=1, limit_categories=None, category=["cpu"],
                               sample_per_category=1, dry_run=False)
    assert asyncio.run(cli.crawl_provider("sigma", settings, selected)) is True
    assert called == []
    full = SimpleNamespace(limit_pages=None, limit_categories=None, category=None,
                           sample_per_category=0, dry_run=False)
    assert asyncio.run(cli.crawl_provider("sigma", settings, full)) is False
    assert called == []


@pytest.mark.parametrize("failure_mode", ["returned", "raised"])
def test_all_providers_start_together_and_one_failure_does_not_stop_others(monkeypatch, failure_mode):
    providers = ("sigma", "elnekhely", "elbadr", "alfrensia", "maximum")
    monkeypatch.setattr(cli, "SPIDERS", dict.fromkeys(providers))
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings("", "Africa/Cairo", 1, 10, 0.35))
    barrier = Barrier(len(providers))
    started = []
    guard = Lock()

    async def fake_crawl(provider, _settings, _args):
        with guard:
            started.append(provider)
        barrier.wait(timeout=5)
        if provider == "elnekhely":
            if failure_mode == "raised":
                raise RuntimeError("startup failed")
            return False
        return True

    monkeypatch.setattr(cli, "crawl_provider", fake_crawl)
    assert cli.main(["run", "--dry-run"]) == 1
    assert set(started) == set(providers)


def test_selected_providers_run_concurrently_without_other_providers(monkeypatch):
    monkeypatch.setattr(cli, "SPIDERS", dict.fromkeys(("sigma", "maximum", "elbadr", "switchplus")))
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings("", "Africa/Cairo", 1, 10, 0.35))
    barrier = Barrier(2)
    started = []
    guard = Lock()

    def fake_run(provider, _settings, _args):
        with guard:
            started.append(provider)
        barrier.wait(timeout=5)
        return True

    monkeypatch.setattr(cli, "run_provider", fake_run)
    assert cli.main(["run", "--dry-run", "--provider", "sigma",
                     "--provider", "maximum"]) == 0
    assert set(started) == {"sigma", "maximum"}


def test_authoritative_run_records_every_provider_outcome(monkeypatch):
    monkeypatch.setattr(cli, "SPIDERS", dict.fromkeys(("sigma", "twob", "switchplus")))
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings("test-db", "Africa/Cairo", 1, 10, 0.35))
    class FakeLock:
        def execute(self, *_):
            pass
        def close(self):
            pass
    monkeypatch.setattr(cli, "acquire_run_lock", lambda *_: FakeLock())
    monkeypatch.setattr(cli, "begin_crawl_runs", lambda _url, providers:
                        {provider: index for index, provider in enumerate(providers, 1)})
    recorded = []
    monkeypatch.setattr(cli, "finish_crawl_run", lambda _url, run_id, success:
                        recorded.append((run_id, success)))
    monkeypatch.setattr(cli, "run_provider", lambda provider, *_: provider == "sigma")
    assert cli.main(["run", "--provider", "sigma", "--provider", "twob"]) == 1
    assert set(recorded) == {(1, True), (2, False)}
