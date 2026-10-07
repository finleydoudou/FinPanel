"""Dataset identities, no fallback, provenance and independently mutated future evidence."""

from dataclasses import replace

import pytest
from test_panel_engine import pinned
from test_snapshots_pipeline import snapshot, sources

from finpanel import panel
from finpanel.errors import ValidationError
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore, SnapshotError


def test_coverage_and_trace(tmp_path):
    store, req = pinned(tmp_path)
    result = panel.build(req, store=store)
    coverage = result.coverage()
    assert coverage["requested_cells"] == len(coverage["cells"]) == 4
    assert coverage["states"] == {
        "resolved_reported": 2,
        "resolved_derived": 1,
        "insufficient_evidence": 1,
    }
    assert coverage["reasons"]["insufficient_cumulative_operands"] == 1
    for counts in coverage["by_dimension"].values():
        assert sum(c["count"] for c in counts) == 4
    detail = result.inspect(result.rows[2].row_id)
    assert detail["canonical_result"].minuend.selected
    assert detail["evidence"]["selected"][0][0]["source"].response_sha256
    assert detail["evidence"]["selected"][0][0]["eligibility"].eligible_as_of
    assert detail["evidence"]["revision_groups"][0][0]["selected_observation_ids"]
    assert result.receipt.semantic["artifacts"]
    with pytest.raises(ValidationError):
        result.inspect("unknown")


def test_serialized_replay_pinned_old_and_new(tmp_path):
    store, req = pinned(tmp_path)
    old = panel.build(req, store=store)
    newer = snapshot(store, 101, "2026-02-01T00:00:00Z")
    new = panel.build(replace(req, snapshot_id=newer.snapshot_id), store=store)
    assert new.rows[1].value == 101
    receipt = panel.PanelReceipt(**loads(dumps(old.receipt).encode()))
    replay = panel.reproduce(receipt, store=store)
    assert replay.receipt.receipt_id == old.receipt.receipt_id
    assert replay.rows[1].value == 100
    assert all(r.snapshot_id == req.snapshot_id for r in replay.rows)
    assert new.receipt.receipt_id != old.receipt.receipt_id


@pytest.mark.parametrize("damage", ["missing", "corrupt", "receipt"])
def test_replay_fails_closed(tmp_path, damage):
    store, req = pinned(tmp_path)
    result = panel.build(req, store=store)
    if damage == "receipt":
        receipt = replace(result.receipt, receipt_id="0" * 64)
    else:
        artifact = store._artifact(store.load(req.snapshot_id).manifest["artifacts"][0])
        path = store.root / artifact.locator
        if damage == "missing":
            path.unlink()
        else:
            path.write_bytes(b"corrupt")
        receipt = result.receipt
    with pytest.raises(SnapshotError):
        panel.reproduce(receipt, store=store)


def test_future_filing_fact_calendar_mutation_does_not_change_decisions(tmp_path):
    store, req = pinned(tmp_path)
    old = panel.build(req, store=store)
    raws = sources()
    facts, filings = (r.json() for r in raws)
    obs = facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    future = dict(obs[0], val=99999999, accn="0000000001-26-000001", filed="2026-01-01", fy=2099)
    obs.append(future)
    recent = filings["filings"]["recent"]
    for key, value in {
        "accessionNumber": future["accn"],
        "reportDate": "2021-12-31",
        "form": "10-K",
        "filingDate": "2026-01-01",
        "acceptanceDateTime": "2026-01-01T15:00:00Z",
    }.items():
        recent[key].append(value)
    new = store.create(
        [
            store.capture(
                replace(raw, body=dumps(data).encode()),
                source_family=family,
                cik=1,
                authenticity="synthetic",
            )
            for raw, data, family in zip(
                raws, [facts, filings], ["companyfacts", "submissions"], strict=True
            )
        ],
        scope="future mutation",
    )
    changed = panel.build(replace(req, snapshot_id=new.snapshot_id), store=store)

    def decisions(r):
        return [(x.state, x.value, x.period_start, x.period_end, x.accessions) for x in r.rows]

    assert decisions(old) == decisions(changed)
    assert panel.reproduce(old.receipt, store=store).receipt.receipt_id == old.receipt.receipt_id


def test_recent_only_is_explicit_not_fallback(tmp_path):
    store = EvidenceStore(tmp_path)
    raws = sources()
    data = raws[1].json()
    data["filings"]["files"] = [{"name": "CIK0000000001-submissions-001.json", "filingCount": 1}]
    raws[1] = replace(raws[1], body=dumps(data).encode())
    snap = store.create(
        [
            store.capture(raw, source_family=f, cik=1, authenticity="synthetic")
            for raw, f in zip(raws, ["companyfacts", "submissions"], strict=True)
        ],
        scope="missing history",
    )
    from test_panel_contract import request

    req = request(fiscal_years=[2021], periods=["Q1"], snapshot_id=snap.snapshot_id)
    complete = panel.build(req, store=store)
    assert complete.rows[0].state == "insufficient_evidence"
    assert "pinned_snapshot_missing_evidence" in complete.rows[0].reasons
    limited = panel.build(replace(req, timeline_scope="recent_only"), store=store)
    assert limited.rows[0].value == 100
    assert "timeline_recent_only" in limited.rows[0].reasons
    assert limited.receipt.semantic["request"]["timeline_scope"] == "recent_only"
