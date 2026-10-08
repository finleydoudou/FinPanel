from dataclasses import replace

import pytest
from test_panel_engine import pinned
from test_snapshots_pipeline import sources

from finpanel import panel, revisions
from finpanel._reuse import evaluation_reuse
from finpanel.errors import ValidationError
from finpanel.panel.engine import row_record
from finpanel.sec.companyfacts import parse_companyfacts
from finpanel.snapshots.store import digest


def test_reuse_preserves_all_rows_and_receipt(tmp_path):
    store, req = pinned(tmp_path / "store")
    with evaluation_reuse(enabled=False) as before:
        a = panel.build(req, store=store)
    with evaluation_reuse() as after:
        b = panel.build(req, store=store)
    assert digest([row_record(r) for r in a.rows]) == digest([row_record(r) for r in b.rows])
    assert a.receipt.receipt_id == b.receipt.receipt_id
    assert before.builds["companyfacts_parse"] > after.builds["companyfacts_parse"] == 1
    assert after.hits["revision_analysis"] > 0
    assert after.cache == {}


def test_parse_reuse_isolates_changed_bytes_and_closed_scopes():
    first = sources()[0]
    changed = sources(101)[0]
    with evaluation_reuse() as reuse:
        a = parse_companyfacts(first)
        assert parse_companyfacts(first) is a
        b = parse_companyfacts(changed)
        assert b.records[0].value != a.records[0].value
        assert reuse.builds["companyfacts_parse"] == 2
    assert parse_companyfacts(first) is not a
    with evaluation_reuse():
        assert parse_companyfacts(first) is not a


def test_reuse_still_rejects_tampered_view(tmp_path):
    store, req = pinned(tmp_path / "store")
    result = panel.build(req, store=store)
    view = result.results[result.rows[0].row_id].candidates.evidence[0]
    with evaluation_reuse():
        revisions.analyze(view)
        with pytest.raises(ValidationError):
            revisions.analyze(replace(view, mode="retrospective"))


def test_reuse_cannot_carry_later_resolution_into_earlier_cutoff(tmp_path):
    store, req = pinned(tmp_path / "store", as_of=["2025-01-01T00:00:00Z"])
    early = replace(req, as_of=("2021-01-01T00:00:00Z",))
    expected = panel.build(early, store=store)
    with evaluation_reuse():
        later = panel.build(req, store=store)
        assert later.rows[0].value == 600
        actual = panel.build(early, store=store)
        assert all(row.value is None for row in actual.rows)
        assert actual.receipt.receipt_id == expected.receipt.receipt_id
