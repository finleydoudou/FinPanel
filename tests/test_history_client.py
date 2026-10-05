import httpx
import pytest

from finpanel.errors import CacheMissError, SECRequestError, ValidationError
from finpanel.sec.client import SECClient

NAME = "CIK0000000001-submissions-001.json"


def test_historical_endpoint_cache_refresh_and_throttle(tmp_path, limiter, clock):
    calls = []
    body = b'{"accessionNumber":["0000000001-20-000001"]}'

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=body)

    with SECClient(
        "test", cache_dir=tmp_path, limiter=limiter, transport=httpx.MockTransport(handler)
    ) as client:
        assert client.historical_submissions(1, NAME).body == body
        assert client.historical_submissions(1, NAME).from_cache
        assert not client.historical_submissions(1, NAME, refresh=True).from_cache
    assert calls == [f"https://data.sec.gov/submissions/{NAME}"] * 2
    assert clock.sleeps == [1.0]


@pytest.mark.parametrize(
    "name",
    [
        "../test.json",
        "https://data.sec.gov/x",
        "CIK0000000002-submissions-001.json",
        "CIK0000000001-submissions-001.json?x=y",
        None,
    ],
)
def test_historical_filename_validation(tmp_path, name):
    with SECClient(offline=True, cache_dir=tmp_path) as client:
        with pytest.raises(ValidationError):
            client.historical_submissions(1, name)


def test_offline_missing_and_refresh_fail_without_network(tmp_path):
    with SECClient(offline=True, cache_dir=tmp_path) as client:
        with pytest.raises(CacheMissError):
            client.submissions(1)
        with pytest.raises(ValidationError):
            client.submissions(1, refresh=True)


@pytest.mark.parametrize("body", [b"{}", b'{"accessionNumber":{}}', b"<html>denied</html>"])
def test_history_bad_envelope_not_cached(tmp_path, limiter, body):
    with SECClient(
        "test",
        cache_dir=tmp_path,
        limiter=limiter,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
    ) as client:
        with pytest.raises(ValidationError):
            client.historical_submissions(1, NAME)
    assert not list(tmp_path.rglob("*.json"))


def test_history_403_not_retried(tmp_path, limiter):
    with SECClient(
        "test",
        cache_dir=tmp_path,
        limiter=limiter,
        transport=httpx.MockTransport(lambda r: httpx.Response(403)),
    ) as client:
        with pytest.raises(SECRequestError) as exc:
            client.historical_submissions(1, NAME)
    assert exc.value.status == 403 and exc.value.attempts == 1


def test_timeline_loads_all_history_files_and_refreshes_all(tmp_path, limiter):
    from finpanel import filings

    names = ["CIK0000000001-submissions-002.json", NAME]
    seen = []

    def handler(request):
        url = str(request.url)
        seen.append(url)
        if url.endswith("CIK0000000001.json"):
            return httpx.Response(
                200,
                json={"cik": 1, "filings": {"recent": {}, "files": [{"name": n} for n in names]}},
            )
        number = 1 if url.endswith(NAME) else 2
        return httpx.Response(
            200,
            json={"accessionNumber": [f"0000000001-20-{number:06d}"], "filingDate": ["2020-01-01"]},
        )

    with SECClient(
        "test", cache_dir=tmp_path, limiter=limiter, transport=httpx.MockTransport(handler)
    ) as client:
        data = filings.timeline(1, client=client)
        assert data.historical_files_loaded == tuple(sorted(names))
        assert len(data.sources) == 3 and len(data) == 2
        assert len(filings.timeline(1, client=client)) == 2
        assert len(seen) == 3
        filings.timeline(1, client=client, refresh=True)
        assert len(seen) == 6
        assert seen[:3] == seen[3:]
