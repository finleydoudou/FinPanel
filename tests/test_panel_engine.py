from dataclasses import replace
from decimal import Decimal

import pytest
from test_panel_contract import request
from test_snapshots_pipeline import snapshot, sources

from finpanel import panel
from finpanel.cache import FileCache
from finpanel.errors import ValidationError
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps
from finpanel.snapshots import EvidenceStore, SnapshotError


def pinned(tmp_path, **changes):
    store = EvidenceStore(tmp_path)
    s = snapshot(store)
    req = request(
        fiscal_years=[2021], periods=["FY", "Q1", "Q2", "Q3"], snapshot_id=s.snapshot_id, **changes
    )
    return store, req


def test_engine_reported_derived_unavailable_and_reuse(tmp_path):
    store, req = pinned(tmp_path)
    r = panel.build(req, store=store)
    assert [(x.period, x.state, x.value) for x in r.rows] == [
        ("FY", "resolved_reported", 600),
        ("Q1", "resolved_reported", 100),
        ("Q2", "resolved_derived", 150),
        ("Q3", "insufficient_evidence", None),
    ]
    assert r.performance["candidate_builds"] == 1
    assert r.performance["candidate_reuses"] == 3
    assert all(x.snapshot_id == req.snapshot_id for x in r.rows)
    assert (
        r.inspect(r.rows[2].row_id)["canonical_result"].minuend.evidence_snapshot_id
        == req.snapshot_id
    )
    again = panel.build(req, store=store)
    assert r.receipt.receipt_id == again.receipt.receipt_id


def test_failure_isolation_and_strict(tmp_path):
    store, req = pinned(tmp_path, entities=[1, 2])
    r = panel.build(req, store=store)
    assert len(r.rows) == 8
    assert all("pinned_snapshot_missing_evidence" in x.reasons for x in r.rows[4:])
    with pytest.raises(panel.PanelBuildError):
        panel.build(replace(req, errors="raise"), store=store)


def test_no_future_evidence_and_multiple_cutoffs(tmp_path):
    store, req = pinned(tmp_path, as_of=["2021-01-01T00:00:00Z", "2025-01-01T00:00:00Z"])
    r = panel.build(req, store=store)
    assert all(x.value is None for x in r.rows[:4])
    assert r.rows[4].value == 600


def test_required_verification_and_no_external_client(tmp_path):
    store, req = pinned(tmp_path, source_verification="required")
    r = panel.build(req, store=store)
    assert r.rows[0].state == "source_verification_failed"
    assert r.rows[0].value is None
    with pytest.raises(ValidationError):
        panel.build(req, store=store, client=object())


def test_unpinned_offline(tmp_path):
    cache = FileCache(tmp_path)
    for raw in sources():
        cache.put(raw)
    with SECClient(cache=cache, offline=True) as client:
        r = panel.build(request(fiscal_years=[2021], periods=["Q1"]), client=client)
    assert r.rows[0].value == 100
    assert r.rows[0].evidence_mode == "unsnapshotted_within_build"
    with pytest.raises(SnapshotError):
        panel.reproduce(r.receipt, store=EvidenceStore(tmp_path / "empty"))


def test_conflict_and_exact_decimal(tmp_path):
    store = EvidenceStore(tmp_path)
    raws = sources(Decimal("1000000000000000000000000.0000000001"))
    data = raws[0].json()
    original = data["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]
    data["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(dict(original, val=99))
    raws[0] = replace(raws[0], body=dumps(data).encode())
    s = store.create(
        [
            store.capture(raw, source_family=f, cik=1, authenticity="synthetic")
            for raw, f in zip(raws, ["companyfacts", "submissions"], strict=True)
        ],
        scope="conflict",
    )
    r = panel.build(
        request(fiscal_years=[2021], periods=["Q1"], snapshot_id=s.snapshot_id), store=store
    )
    assert r.rows[0].state == "conflicted" and r.rows[0].value is None
    assert r.rows[0].conflicts


def test_instant_explicit_end(tmp_path):
    store = EvidenceStore(tmp_path)
    raw = sources()
    data = raw[0].json()
    row = dict(data["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0])
    row.pop("start")
    data["facts"]["us-gaap"]["Assets"] = {"units": {"USD": [row]}}
    raw[0] = replace(raw[0], body=dumps(data).encode())
    s = store.create(
        [
            store.capture(r, source_family=f, cik=1, authenticity="synthetic")
            for r, f in zip(raw, ["companyfacts", "submissions"], strict=True)
        ],
        scope="instant",
    )
    req = request(
        metrics=["assets"], fiscal_years=[2021], periods=["Q1"], snapshot_id=s.snapshot_id
    )
    assert panel.build(req, store=store).rows[0].state == "unsupported"
    req = replace(req, period_ends=(panel.PeriodEnd(1, 2021, "Q1", "2021-03-31"),))
    assert panel.build(req, store=store).rows[0].value == 100


def test_reported_only_and_derived_only_policies(tmp_path):
    store, req = pinned(tmp_path)
    reported = panel.build(replace(req, source_policy="reported_only"), store=store)
    assert reported.rows[1].state == "resolved_reported"
    assert reported.rows[2].value is None and reported.rows[2].state == "unavailable"
    derived = panel.build(replace(req, source_policy="derived_only"), store=store)
    assert derived.rows[0].state == "unsupported"
    assert derived.rows[0].reasons == ("derived_only_requires_quarter",)
    assert derived.rows[1].state == "unsupported"
    assert derived.rows[2].state == "resolved_derived" and derived.rows[2].value == 150


@pytest.mark.parametrize("policy", ["first_reported", "latest_available", "all_available"])
def test_revision_policy_kept_in_result_and_receipt(tmp_path, policy):
    store, req = pinned(tmp_path, revision_policy=policy)
    r = panel.build(req, store=store)
    assert r.rows[1].value == 100
    assert r.inspect(r.rows[1].row_id)["canonical_result"].revision_policy == policy
    assert r.receipt.semantic["request"]["revision_policy"] == policy
    assert r.provenance[r.rows[1].row_id]["policies"]["revision"] == policy
