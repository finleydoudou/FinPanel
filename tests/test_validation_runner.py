from dataclasses import replace

from test_panel_engine import pinned
from test_validation_acquisition import manifest

from finpanel import panel
from finpanel.validation.invariants import check_panel
from finpanel.validation.runner import BenchmarkConfig, run
from finpanel.validation.taxonomy import classify


def test_invariant_detects_tampered_value(tmp_path):
    store, req = pinned(tmp_path / "store")
    result = panel.build(req, store=store)
    assert check_panel(result, store)["failures"] == []
    tampered = replace(result, rows=(replace(result.rows[0], value=601), *result.rows[1:]))
    errors = check_panel(tampered, store)["failures"]
    assert any(x["code"] == "panel_canonical_value" for x in errors)


def test_runner_aggregates_and_replays(tmp_path):
    store, req = pinned(tmp_path / "store")
    cfg = BenchmarkConfig(
        fiscal_years=(2021,),
        as_of=("2025-01-01T00:00:00Z",),
        periods=("FY", "Q1", "Q2"),
        revision_policies=("latest_available",),
    )
    report, receipt, performance = run(
        store, req.snapshot_id, tmp_path / "report", manifest=manifest(), config=cfg
    )
    assert report["requested_cells"] == report["observed_cells"] == 18
    assert report["unexpected_mismatches"] == 0
    assert report["successful_replays"] == 1
    assert report["states"]["resolved_derived"] == 1
    assert receipt["semantic_dataset_hash"] and receipt["report_hash"]
    assert performance["workers"] == 1


def test_taxonomy_separates_absence_from_implementation_failure(tmp_path):
    store, req = pinned(tmp_path / "store")
    row = panel.build(req, store=store).rows[-1]
    assert classify(row, {})["kind"] == "expected_conservatism"
    assert classify(row, {"error_type": "ValueError"})["kind"] == "unexpected_failure"
    missing = replace(row, reasons=("pinned_snapshot_missing_evidence",))
    assert classify(missing, {"error_type": "CacheMissError"}) == {
        "kind": "evidence_gap",
        "categories": ["snapshot_evidence_gap"],
    }


def test_runner_reports_invariant_failures_as_unexpected(tmp_path, monkeypatch):
    from finpanel.validation import runner

    store, req = pinned(tmp_path / "store")
    monkeypatch.setattr(
        runner,
        "check_panel",
        lambda result, store: {
            "checks": 1,
            "failures": [{"category": "internal_invariant_violation", "code": "injected_failure"}],
        },
    )
    report, _, _ = run(
        store,
        req.snapshot_id,
        tmp_path / "report",
        manifest=manifest(),
        config=BenchmarkConfig(
            fiscal_years=(2021,),
            periods=("FY",),
            as_of=("2025-01-01T00:00:00Z",),
            revision_policies=("latest_available",),
            source_verification=False,
        ),
    )
    assert report["unexpected_mismatches"] == 1
    assert report["unexpected_findings"][0]["code"] == "injected_failure"


def test_taxonomy_does_not_infer_observed_dimensions_or_revision_from_caveats(tmp_path):
    store, req = pinned(tmp_path / "store")
    row = panel.build(req, store=store).rows[-1]
    row = replace(
        row,
        reasons=(
            "company_level_scope_only; original_instance_dimensions_not_proven_equal",
            "revision_or_scope_conflict",
            "multiple_supported_concept_scopes",
            "insufficient_cumulative_operands",
        ),
    )
    categories = classify(row, {})["categories"]
    assert "dimensioned_fact" not in categories
    assert "incompatible_revision_operands" not in categories
    assert "insufficient_cumulative_facts" in categories
    confirmed = replace(
        row, reasons=("dimensioned_arithmetic_not_supported", "unpaired_value_revision")
    )
    categories = classify(confirmed, {})["categories"]
    assert "dimensioned_fact" in categories and "incompatible_revision_operands" in categories
