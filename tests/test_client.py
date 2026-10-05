import httpx
import pytest

from finpanel.errors import SECRequestError, SECTimeoutError, ValidationError
from finpanel.sec.client import SECClient


def test_cache_refresh_headers_urls(tmp_path, limiter, raw):
    calls = []

    def handler(request):
        calls.append(request)
        endpoint = "companyfacts" if "/companyfacts/" in str(request.url) else "submissions"
        return httpx.Response(200, content=raw(endpoint).body)

    with SECClient(
        "FinPanel test contact@example.com",
        cache_dir=tmp_path,
        limiter=limiter,
        transport=httpx.MockTransport(handler),
    ) as client:
        first = client.submissions(320193)
        cached = client.submissions("0000320193")
        fresh = client.submissions(320193, refresh=True)
        client.companyfacts(320193)
    assert len(calls) == 3
    assert first.body == cached.body == fresh.body
    assert cached.from_cache and not fresh.from_cache
    assert str(calls[0].url) == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert str(calls[-1].url) == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    assert calls[0].headers["User-Agent"] == "FinPanel test contact@example.com"
    assert calls[0].extensions["timeout"]["read"] == 30.0


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retry_transient(tmp_path, limiter, clock, raw, status):
    codes = iter([status, 200])

    def handler(request):
        return httpx.Response(next(codes), content=raw().body, headers={"Retry-After": "4"})

    with SECClient(
        "test", cache_dir=tmp_path, limiter=limiter, transport=httpx.MockTransport(handler)
    ) as client:
        client.companyfacts(320193)
    assert clock.sleeps == [4.0]


@pytest.mark.parametrize("status", [301, 400, 403, 404])
def test_no_retry_permanent(tmp_path, limiter, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://elsewhere.invalid"})

    with SECClient(
        "test", cache_dir=tmp_path, limiter=limiter, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(SECRequestError) as exc:
            client.submissions(1)
    assert len(calls) == 1
    assert exc.value.status == status
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError]
)
def test_transport_retry_budget(tmp_path, limiter, clock, error):
    def handler(request):
        raise error("synthetic transport failure", request=request)

    with SECClient(
        "test",
        cache_dir=tmp_path,
        limiter=limiter,
        max_retries=2,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            SECTimeoutError if error is httpx.ReadTimeout else SECRequestError
        ) as exc:
            client.submissions(1)
    assert exc.value.attempts == 3
    assert clock.sleeps == [1.0, 2.0]


def test_http_retry_exhausted(tmp_path, limiter):
    with SECClient(
        "test",
        cache_dir=tmp_path,
        limiter=limiter,
        max_retries=1,
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
    ) as client:
        with pytest.raises(SECRequestError) as exc:
            client.submissions(1)
    assert exc.value.attempts == 2
    assert exc.value.status == 503


@pytest.mark.parametrize(
    "body", [b"<html>denied</html>", b"{}", b'{"cik":2,"filings":{}}', b'{"cik":1,"filings":[]}']
)
def test_invalid_response_not_cached(tmp_path, limiter, body):
    with SECClient(
        "test",
        cache_dir=tmp_path,
        limiter=limiter,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
    ) as client:
        with pytest.raises(ValidationError):
            client.submissions(1)
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize(
    "value, expected",
    [("Mon, 05 Oct 2026 00:00:07 GMT", 7), ("bad", 0), ("-5", 0), ("inf", 0), (None, 0)],
)
def test_retry_after_date(now, tmp_path, value, expected):
    with SECClient("test", cache_dir=tmp_path, now=now) as client:
        assert client._retry_after(value) == expected


def test_rate_limiter(limiter, clock):
    limiter.wait()
    limiter.wait()
    limiter.defer(10)
    limiter.wait()
    assert clock.sleeps == [1.0, 10.0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"user_agent": ""},
        {"user_agent": None},
        {"user_agent": "bad\nheader"},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"max_retries": -1},
        {"max_retries": True},
    ],
)
def test_invalid_config(kwargs):
    with pytest.raises(ValidationError):
        SECClient(**({"user_agent": "test"} | kwargs))


def test_environment_user_agent(monkeypatch, tmp_path, limiter, raw):
    monkeypatch.setenv("FINPANEL_SEC_USER_AGENT", "Research contact@example.org")
    seen = []

    def handler(request):
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, content=raw().body)

    with SECClient(
        cache_dir=tmp_path, limiter=limiter, transport=httpx.MockTransport(handler)
    ) as client:
        client.companyfacts(320193)
    assert seen == ["Research contact@example.org"]


def test_explicit_user_agent_overrides_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("FINPANEL_SEC_USER_AGENT", "environment contact@example.org")
    with SECClient("explicit contact@example.org", cache_dir=tmp_path) as client:
        assert client._http.headers["User-Agent"] == "explicit contact@example.org"
    with pytest.raises(ValidationError):
        SECClient("")


def test_failed_refresh_preserves_cache(tmp_path, limiter, raw):
    from dataclasses import replace

    from finpanel.cache import FileCache

    cache = FileCache(tmp_path)
    source = replace(raw(), url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json")
    cache.put(source)
    with SECClient(
        "test",
        cache=cache,
        limiter=limiter,
        transport=httpx.MockTransport(lambda r: httpx.Response(403)),
    ) as client:
        with pytest.raises(SECRequestError) as exc:
            client.companyfacts(320193, refresh=True)
        assert exc.value.attempts == 1
        assert client.companyfacts(320193).body == source.body
    assert len(list(tmp_path.glob("raw/requests/*/versions/*.json"))) == 1
