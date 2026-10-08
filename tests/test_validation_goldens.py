"""Tier A raw-byte goldens and independently read original XML, always offline."""

from decimal import Decimal
from pathlib import Path

import pytest

from finpanel.serialization import loads
from finpanel.snapshots import EvidenceStore, SnapshotError
from finpanel.validation.fixtures import import_fixtures
from finpanel.validation.goldens import audit_sources, validate_goldens
from finpanel.xbrl.discovery import SourceDocument
from finpanel.xbrl.parser import parse_instance

ROOT = Path(__file__).parent


@pytest.fixture(scope="module")
def tier_a(tmp_path_factory):
    store = EvidenceStore(tmp_path_factory.mktemp("tier-a") / "store")
    snap = import_fixtures(ROOT / "fixtures/broad", store)
    return store, snap


def test_156_independently_audited_cases(tier_a):
    store, snap = tier_a
    result = validate_goldens(store, snap.snapshot_id, ROOT / "golden/broad.json")
    assert result["case_count"] == 156
    assert result["issuer_count"] == 13
    assert result["unexpected_mismatches"] == 0, [f for f in result["findings"] if not f["passed"]]
    assert result["matched"] == 156
    assert result["invariant_checks"] > 1000
    assert any(f["expected_state"] == "conflicted" for f in result["findings"])
    assert any(f["expected_state"] == "ambiguous_period" for f in result["findings"])


def test_independent_original_xml_literals(tier_a):
    store, snap = tier_a
    cases = loads((ROOT / "golden/broad-edges.json").read_bytes())["xbrl_cases"]
    assert len(cases) == 39 and len({c["cik"] for c in cases}) == 13
    parsed = {}
    for case in cases:
        sha = case["artifact_sha256"]
        if sha not in parsed:
            a = next(a for a in snap.manifest["artifacts"] if a["sha256"] == sha)
            raw = store.raw(store._artifact(a))
            doc = SourceDocument(
                a["cik"],
                a["accession"],
                "10-K",
                None,
                a["source_url"].rsplit("/", 1)[1],
                a["source_url"],
                "instance",
                None,
                None,
                "EX-101.INS",
                (),
                a["sha256"],
                a["retrieved_at"],
            )
            parsed[sha] = parse_instance(raw, doc)
        instance = parsed[sha]
        fact = next(
            f
            for f in instance.facts
            if f.provenance.pointer == f"/xbrli:xbrl/*[{case['position']}]"
        )
        assert fact.concept == case["concept"] and fact.lexical_value == case["lexical"]
        assert fact.value == Decimal(case["value"]) and fact.numeric.decimals == case["decimals"]
        context = next(c for c in instance.contexts if c.context_id == fact.context_ref)
        assert bool(context.dimensions) == case["dimensioned"]


def test_golden_literal_tampering_is_detected(tier_a):
    store, snap = tier_a
    case = loads((ROOT / "golden/broad.json").read_bytes())["cases"][0]
    a = next(a for a in snap.manifest["artifacts"] if a["sha256"] == case["sources"][0]["sha256"])
    raw = {a["sha256"]: store.raw(store._artifact(a)).json()}
    case["expected_value"] += 1
    assert "golden_reported_literal_mismatch" in audit_sources(case, raw)


def test_missing_pinned_object_cannot_substitute_live(tier_a, tmp_path):
    store, snap = tier_a
    # Separate store with manifest only; no mutation of module fixture.
    from finpanel.serialization import dumps
    from finpanel.snapshots.store import _publish

    empty = EvidenceStore(tmp_path)
    _publish(
        empty.root / "snapshots" / f"{snap.snapshot_id}.json",
        dumps(dict(snapshot_id=snap.snapshot_id, **snap.manifest)).encode(),
    )
    with pytest.raises(SnapshotError):
        validate_goldens(empty, snap.snapshot_id, ROOT / "golden/broad.json")


def test_raw_json_edge_ledger(tier_a):
    from datetime import date

    store, snap = tier_a
    ledger = loads((ROOT / "golden/broad-edges.json").read_bytes())
    raw_by_sha = {}
    checked = 0
    for kind, examples in ledger["examples"].items():
        if kind in {"decimals_metadata", "dimensioned_original_context", "zero_original_fact"}:
            continue  # Independently checked by the XML literal test above.
        for example in examples:
            sources = example.get("sources", [example])
            values = []
            for source in sources:
                sha = source["sha256"]
                if sha not in raw_by_sha:
                    artifact = next(a for a in snap.manifest["artifacts"] if a["sha256"] == sha)
                    raw_by_sha[sha] = store.raw(store._artifact(artifact)).json()
                fact = raw_by_sha[sha]
                for part in source["pointer"].split("/")[1:]:
                    fact = fact[int(part)] if isinstance(fact, list) else fact[part]
                assert fact["val"] == source["value"]
                assert fact["accn"] == source["accession"]
                assert fact["end"] == source["end"]
                assert fact.get("start") == source["start"]
                values.append(fact["val"])
                if kind.startswith(("52_week", "53_week")):
                    days = (
                        date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])
                    ).days + 1
                    assert days == (364 if kind.startswith("52") else 371)
                if kind.startswith("negative"):
                    assert fact["val"] < 0
                if kind == "zero_standard_concept":
                    assert fact["val"] == 0
                if kind == "large_values":
                    assert abs(fact["val"]) >= 100_000_000_000
                if kind == "amended_filing_observation":
                    assert fact["form"].endswith("/A")
                checked += 1
            if kind == "comparative_values_changed_cause_unestablished":
                assert len(set(values)) > 1
    assert checked == 36
