from dataclasses import replace

import pytest

from finpanel.cache import FileCache
from finpanel.errors import CacheError


def test_cache_bytes_versions_and_metadata(tmp_path, raw):
    cache = FileCache(tmp_path)
    first = raw()
    assert cache.get(first.url) is None
    cache.put(first)
    cached = cache.get(first.url)
    assert cached.body == first.body
    assert cached.retrieved_at == first.retrieved_at
    assert cached.from_cache
    second = replace(first, body=first.body + b"\n", retrieved_at="2026-10-06T00:00:00+00:00")
    cache.put(second)
    assert cache.get(first.url).body == second.body
    assert len(list(tmp_path.glob("raw/objects/*.json"))) == 2
    assert len(list(tmp_path.glob("raw/requests/*/versions/*.json"))) == 2


@pytest.mark.parametrize("mode", ["corrupt", "missing", "bad_index"])
def test_cache_corruption_is_explicit(tmp_path, raw, mode):
    cache = FileCache(tmp_path)
    response = raw()
    cache.put(response)
    obj = next(tmp_path.glob("raw/objects/*.json"))
    if mode == "corrupt":
        obj.write_bytes(b"{}")
    elif mode == "missing":
        obj.unlink()
    else:
        next(tmp_path.glob("raw/requests/*/latest.json")).write_text("{}")
    with pytest.raises(CacheError):
        cache.get(response.url)
