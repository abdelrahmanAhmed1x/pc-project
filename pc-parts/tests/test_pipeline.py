import pytest

from pc_parts import pipeline
from pc_parts.config import Settings


class FakeResult:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return (self.value,)

    def fetchall(self):
        return self.value


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, _params=None):
        if "pg_try_advisory_lock" in sql:
            return FakeResult(True)
        if "FROM identity_batches" in sql:
            return FakeResult([])
        return FakeResult(None)


def settings():
    return Settings("postgresql://unused", "Africa/Cairo", 1.0, 10, 0.35)


def test_full_pipeline_submits_waits_applies_and_reindexes(monkeypatch):
    steps = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(pipeline.psycopg, "connect", lambda *_a, **_kw: FakeConnection())
    monkeypatch.setattr(pipeline, "crawl_main", lambda *_a, **_kw: steps.append("crawl") or 0)
    prepared = iter(({"listings": 2, "deterministic_decisions": 1, "reused_decisions": 0,
                      "luna_requests": 2, "reserved_max_usd": "0.01"},
                     {"listings": 2, "deterministic_decisions": 0, "reused_decisions": 0,
                      "luna_requests": 0, "reserved_max_usd": "0"}))
    monkeypatch.setattr(pipeline, "prepare", lambda *_a: steps.append("prepare") or next(prepared))
    monkeypatch.setattr(pipeline, "submit", lambda *_a: steps.append("submit") or
                        {"batch_id": "batch-1", "requests": 2})
    monkeypatch.setattr(pipeline, "_wait_for_batch", lambda *_a: steps.append("wait"))
    monkeypatch.setattr(pipeline, "_apply_all", lambda *_a: steps.append("apply") or 1)
    monkeypatch.setattr(pipeline, "_reindex", lambda *_a: steps.append("reindex"))

    result = pipeline.execute(settings(), poll_seconds=1)
    assert steps == ["crawl", "prepare", "submit", "wait", "prepare", "apply", "reindex"]
    assert result["luna_requests"] == 2 and result["merged"] == 1


def test_missing_api_key_prevents_long_crawl(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(pipeline, "crawl_main", lambda *_a, **_kw: pytest.fail("crawl started"))
    with pytest.raises(RuntimeError, match="no crawl started"):
        pipeline.execute(settings())


def test_apply_existing_uses_collected_decisions_without_crawl_or_model(monkeypatch):
    steps = []
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(pipeline.psycopg, "connect", lambda *_a, **_kw: FakeConnection())
    monkeypatch.setattr(pipeline, "crawl_main", lambda *_a, **_kw: pytest.fail("crawl started"))
    monkeypatch.setattr(pipeline, "prepare", lambda *_a, **_kw: pytest.fail("model preparation started"))
    monkeypatch.setattr(pipeline, "submit", lambda *_a, **_kw: pytest.fail("model batch submitted"))
    monkeypatch.setattr(pipeline, "_apply_all", lambda *_a: steps.append("apply") or 2)
    monkeypatch.setattr(pipeline, "_reindex", lambda *_a: steps.append("reindex"))
    result = pipeline.execute(settings(), apply_existing=True)
    assert steps == ["apply", "reindex"]
    assert result["merged"] == 2 and result["luna_requests"] == 0


def test_failed_crawl_still_resolves_committed_offers_and_reindexes(monkeypatch):
    steps = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(pipeline.psycopg, "connect", lambda *_a, **_kw: FakeConnection())
    monkeypatch.setattr(pipeline, "crawl_main", lambda *_a, **_kw: steps.append("crawl") or 1)
    monkeypatch.setattr(pipeline, "prepare", lambda *_a: steps.append("prepare") or
                        {"listings": 0, "deterministic_decisions": 0, "reused_decisions": 0,
                         "luna_requests": 0, "reserved_max_usd": "0"})
    monkeypatch.setattr(pipeline, "_apply_all", lambda *_a: steps.append("apply") or 0)
    monkeypatch.setattr(pipeline, "_reindex", lambda *_a: steps.append("reindex"))
    with pytest.raises(RuntimeError, match="provider crawls failed"):
        pipeline.execute(settings())
    assert steps == ["crawl", "prepare", "apply", "reindex"]


def test_reindex_invokes_real_backend_command(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    pipeline._reindex("postgresql://test-only")
    args, kwargs = calls[0]
    assert args[0] == ["go", "run", "./cmd/reindex"]
    assert (kwargs["cwd"] / "cmd" / "reindex" / "main.go").is_file()
    assert kwargs["env"]["DATABASE_URL"] == "postgresql://test-only"
    assert kwargs["check"] is True
