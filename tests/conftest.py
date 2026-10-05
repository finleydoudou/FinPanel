from datetime import UTC, datetime
from pathlib import Path

import pytest

from finpanel.models import RawResponse
from finpanel.sec.client import RateLimiter
from finpanel.serialization import dumps

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw():
    def make(endpoint="companyfacts", ticker="aapl", data=None):
        body = (
            (FIXTURES / f"{ticker}_{endpoint}.json").read_bytes()
            if data is None
            else dumps(data).encode()
        )
        return RawResponse(
            f"https://fixture.invalid/{ticker}/{endpoint}", body, "2026-10-05T00:00:00+00:00"
        )

    return make


class Clock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def limiter(clock):
    return RateLimiter(monotonic=clock.monotonic, sleep=clock.sleep)


@pytest.fixture
def now():
    return lambda: datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
def forbid_live_http(monkeypatch):
    import httpx

    def fail(*args, **kwargs):
        raise AssertionError("Routine tests must not make live HTTP requests")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail)
    monkeypatch.delenv("FINPANEL_SEC_USER_AGENT", raising=False)


@pytest.fixture
def historical_cache(tmp_path):
    from finpanel.cache import FileCache
    from finpanel.serialization import loads

    cache = FileCache(tmp_path / "authentic-cache")
    for folder in (FIXTURES / "sec", FIXTURES / "history"):
        manifest = loads((folder / "manifest.json").read_bytes())
        for filename, meta in manifest["files"].items():
            if meta["cik"] == "0000320193" and "companyfacts" not in filename:
                source = RawResponse(
                    meta["source_url"], (folder / filename).read_bytes(), meta["retrieved_at"]
                )
                assert source.sha256 == meta["sha256"]
                cache.put(source)
    return cache
