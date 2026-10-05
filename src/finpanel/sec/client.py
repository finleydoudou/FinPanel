"""Synchronous SEC JSON client. No redirects, HTML fallback, or rate-limit bypass."""

import logging
import math
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Self

import httpx

from finpanel.cache import FileCache
from finpanel.errors import SECRequestError, SECTimeoutError, ValidationError
from finpanel.models import RawResponse
from finpanel.sec.common import normalize_cik

logger = logging.getLogger(__name__)
BASE = "https://data.sec.gov"
RETRYABLE = {429, 500, 502, 503, 504}


class RateLimiter:
    """Shared by default across clients in this process; callers coordinate other processes."""

    def __init__(
        self,
        interval: float = 1.0,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not math.isfinite(interval) or interval < 0.2:
            raise ValidationError("Request interval must be finite and at least 0.2 seconds")
        self.interval = interval
        self._clock = monotonic
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._next - self._clock()
            if delay > 0:
                self._sleep(delay)
            self._next = self._clock() + self.interval

    def defer(self, seconds: float) -> None:
        with self._lock:
            self._next = max(self._next, self._clock() + seconds)


_DEFAULT_LIMITER = RateLimiter()


class SECClient:
    def __init__(
        self,
        user_agent: str | None = None,
        *,
        cache: FileCache | None = None,
        cache_dir: str | Path = ".finpanel-cache",
        timeout: float = 30.0,
        max_retries: int = 3,
        limiter: RateLimiter | None = None,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if user_agent is None:
            user_agent = os.environ.get("FINPANEL_SEC_USER_AGENT")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValidationError(
                "Set FINPANEL_SEC_USER_AGENT or pass a descriptive User-Agent "
                "including your contact information"
            )
        if any(ord(c) < 32 or ord(c) > 126 for c in user_agent):
            raise ValidationError("User-Agent must contain printable ASCII only")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValidationError("timeout must be finite and positive")
        if type(max_retries) is not int or not 0 <= max_retries <= 10:
            raise ValidationError("max_retries must be an integer between 0 and 10")
        self.cache = cache if cache is not None else FileCache(cache_dir)
        self.max_retries = max_retries
        self.limiter = limiter if limiter is not None else _DEFAULT_LIMITER
        self.now = now
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(timeout),
            transport=transport,
            follow_redirects=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def submissions(self, cik: str | int, *, refresh: bool = False) -> RawResponse:
        return self._get(f"{BASE}/submissions/CIK{normalize_cik(cik)}.json", refresh)

    def companyfacts(self, cik: str | int, *, refresh: bool = False) -> RawResponse:
        return self._get(f"{BASE}/api/xbrl/companyfacts/CIK{normalize_cik(cik)}.json", refresh)

    def _retry_after(self, value: str | None) -> float:
        if value is None:
            return 0.0
        try:
            seconds = float(value)
            return max(seconds, 0.0) if math.isfinite(seconds) else 0.0
        except ValueError:
            try:
                timestamp = parsedate_to_datetime(value)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)
                return max(0.0, (timestamp - self.now()).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return 0.0

    def _get(self, url: str, refresh: bool) -> RawResponse:
        if not refresh:
            cached = self.cache.get(url)
            if cached is not None:
                logger.debug("SEC cache hit %s", url)
                return cached
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            try:
                response = self._http.get(url)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if attempt == self.max_retries:
                    error = (
                        SECTimeoutError
                        if isinstance(exc, httpx.TimeoutException)
                        else SECRequestError
                    )
                    raise error(str(exc), url=url, attempts=attempt + 1) from exc
                self.limiter.defer(2.0**attempt)
                logger.warning("Transient SEC transport failure; retry %s for %s", attempt + 1, url)
                continue
            except httpx.HTTPError as exc:
                raise SECRequestError(str(exc), url=url, attempts=attempt + 1) from exc
            if response.status_code in RETRYABLE:
                delay = max(2.0**attempt, self._retry_after(response.headers.get("Retry-After")))
                self.limiter.defer(delay)
                if attempt < self.max_retries:
                    logger.warning(
                        "SEC HTTP %s; retry %s for %s", response.status_code, attempt + 1, url
                    )
                    continue
            if response.status_code != 200:
                raise SECRequestError(
                    f"SEC returned HTTP {response.status_code}",
                    url=url,
                    attempts=attempt + 1,
                    status=response.status_code,
                )
            raw = RawResponse(url, response.content, self.now().isoformat(), dict(response.headers))
            data = raw.json()
            # Do not cache a JSON error envelope or another company's response as success.
            expected = url.rsplit("CIK", 1)[1].removesuffix(".json")
            if normalize_cik(data.get("cik")) != expected:
                raise ValidationError(f"SEC response CIK does not match request {expected}")
            key = "facts" if "/companyfacts/" in url else "filings"
            if not isinstance(data.get(key), dict):
                raise ValidationError(f"SEC response missing {key} object")
            return self.cache.put(raw)
        raise AssertionError("unreachable")
