"""Synthetic byte-version, immutable-write, manifest and selection adversaries."""

import pytest

from finpanel.models import RawResponse
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore, SnapshotError
from finpanel.snapshots.store import _publish, digest


def capture(
    store,
    body=b'{"cik":1}',
    when="2026-01-01T00:00:00Z",
    url="https://data.sec.gov/submissions/CIK0000000001.json",
):
    return store.capture(
        RawResponse(url, body, when, {"ETag": "abc", "User-Agent": "not retained"}),
        source_family="submissions",
        cik="0000000001",
        authenticity="synthetic",
    )


def test_changed_and_identical_bytes_deduplicate(tmp_path):
    s = EvidenceStore(tmp_path)
    a = capture(s)
    b = capture(s, when="2026-02-01T00:00:00Z")
    c = capture(s, b'{"cik":1,"v":2}')
    assert a.sha256 == b.sha256 != c.sha256 and a.capture_id != b.capture_id
    assert len(list((tmp_path / "objects").iterdir())) == 2
    assert s.raw(a).body == b'{"cik":1}'
    assert a.http_metadata == (("etag", "abc"),)
    assert capture(s) == a


def test_atomic_failure_never_publishes_partial(tmp_path, monkeypatch):
    import os

    def fail(*args):
        raise OSError("interrupted before publication")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(OSError):
        _publish(tmp_path / "object", b"complete")
    assert not list(tmp_path.iterdir())


def test_corruption_not_repaired(tmp_path):
    s = EvidenceStore(tmp_path)
    a = capture(s)
    (tmp_path / a.locator).write_bytes(b"corrupt")
    with pytest.raises(SnapshotError):
        capture(s)
    assert (tmp_path / a.locator).read_bytes() == b"corrupt"


def test_manifest_deterministic_and_scoped(tmp_path):
    s = EvidenceStore(tmp_path)
    a = capture(s)
    b = capture(s, url="https://data.sec.gov/other")
    x = s.create([a, b], scope="two declared artifacts")
    y = s.create([b, a], scope="two declared artifacts")
    assert x.snapshot_id == y.snapshot_id
    assert s.verify(x.snapshot_id).completeness == "complete_for_declared_scope"
    partial = s.create(
        [a], scope="two declared artifacts", required_urls=[a.source_url, b.source_url]
    )
    assert (
        s.verify(partial.snapshot_id).valid
        and s.verify(partial.snapshot_id).completeness == "partial"
    )
    with pytest.raises(SnapshotError):
        s.create([a, capture(s, when="2026-03-01T00:00:00Z")], scope="bad")


@pytest.mark.parametrize(
    "kind", ["missing", "corrupt", "manifest", "format", "malformed", "reference"]
)
def test_integrity_failure(tmp_path, kind):
    s = EvidenceStore(tmp_path)
    a = capture(s)
    snap = s.create([a], scope="one")
    path = tmp_path / "snapshots" / (snap.snapshot_id + ".json")
    if kind == "missing":
        (tmp_path / a.locator).unlink()
    if kind == "corrupt":
        (tmp_path / a.locator).write_bytes(b"changed")
    if kind in {"manifest", "format", "reference"}:
        data = loads(path.read_bytes())
        data["scope"] = "changed"
        if kind == "format":
            data["format"] = "v99"
        if kind == "reference":
            data["relationships"] = [{"from": "bad", "to": "bad", "relation": "supports"}]
        path.write_text(dumps(data))
    if kind == "malformed":
        path.write_text("{broken")
    assert not s.verify(snap.snapshot_id).valid


def test_selection_capture_axis_and_ties(tmp_path):
    s = EvidenceStore(tmp_path)
    a = s.create([capture(s)], scope="one")
    b = s.create([capture(s, b'{"new":2}', when="2026-02-01T00:00:00Z")], scope="one")
    assert s.select(snapshot_id=a.snapshot_id).snapshot_id == a.snapshot_id
    assert s.select(policy="latest_captured", scope="one").snapshot_id == b.snapshot_id
    assert (
        s.select(
            policy="latest_captured_no_later_than",
            scope="one",
            evidence_as_of="2026-01-15T00:00:00Z",
        ).snapshot_id
        == a.snapshot_id
    )
    with pytest.raises(SnapshotError, match="cannot be fabricated"):
        s.select(
            policy="latest_captured_no_later_than",
            scope="one",
            evidence_as_of="2020-01-01T00:00:00Z",
        )
    s.create([capture(s, b'{"other":3}', when="2026-02-01T00:00:00Z")], scope="one")
    with pytest.raises(SnapshotError, match="Conflicting"):
        s.select(policy="latest_captured", scope="one")


def test_valid_hash_but_inconsistent_reference(tmp_path):
    s = EvidenceStore(tmp_path)
    snap = s.create([capture(s)], scope="one")
    m = dict(snap.manifest)
    m["relationships"] = [{"from": "missing", "to": "missing", "relation": "supports"}]
    sid = digest(m)
    (tmp_path / "snapshots" / (sid + ".json")).write_text(dumps({"snapshot_id": sid, **m}))
    assert not s.verify(sid).valid


def test_selection_ignores_filesystem_mtime(tmp_path):
    import os

    s = EvidenceStore(tmp_path)
    a = s.create([capture(s)], scope="one")
    b = s.create([capture(s, when="2026-02-01T00:00:00Z")], scope="one")
    os.utime(tmp_path / "snapshots" / (a.snapshot_id + ".json"), (2000000000, 2000000000))
    assert s.select(policy="latest_captured", scope="one").snapshot_id == b.snapshot_id


def test_source_families_are_explicit_and_not_interchangeable(tmp_path):
    s = EvidenceStore(tmp_path)
    raw = RawResponse(
        "https://www.sec.gov/archive",
        b"opaque captured bytes",
        "2026-01-01T00:00:00Z",
        raw_format="text",
    )
    a = s.capture(raw, source_family="bulk_archive")
    b = s.capture(raw, source_family="filing_text")
    assert a.sha256 == b.sha256 and a.capture_id != b.capture_id
    assert s.raw(a).body == raw.body
    with pytest.raises(SnapshotError):
        s.capture(raw, source_family="invented")


def test_snapshot_metadata_references_http_identity(tmp_path):
    s = EvidenceStore(tmp_path)
    raw = RawResponse(
        "https://data.sec.gov/test",
        b"{}",
        "2026-01-01T01:00:00+01:00",
        {"ETag": "v1", "Last-Modified": "yesterday", "Content-Type": "application/json"},
    )
    a = s.capture(raw, source_family="other_sec")
    assert a.retrieved_at == "2026-01-01T00:00:00+00:00"
    assert dict(a.http_metadata) == {
        "etag": "v1",
        "last-modified": "yesterday",
        "content-type": "application/json",
    }
    assert a.locator == "objects/" + a.sha256 and a.size == 2


@pytest.mark.parametrize(
    "field,value", [("scope", None), ("required_urls", "not a list"), ("artifact_schema", "future")]
)
def test_valid_hash_malformed_schema(tmp_path, field, value):
    s = EvidenceStore(tmp_path)
    snap = s.create([capture(s)], scope="one")
    data = dict(snap.manifest)
    data[field] = value
    sid = digest(data)
    (tmp_path / "snapshots" / (sid + ".json")).write_text(dumps({"snapshot_id": sid, **data}))
    assert not s.verify(sid).valid


def test_concurrent_identical_capture_is_safe(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    s = EvidenceStore(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        artifacts = list(pool.map(lambda _: capture(s), range(8)))
    assert len({a.capture_id for a in artifacts}) == 1
    assert len(list((tmp_path / "objects").iterdir())) == 1
    assert s.raw(artifacts[0]).body == b'{"cik":1}'
