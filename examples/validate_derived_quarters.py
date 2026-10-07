"""Offline derived-quarter benchmark: authentic cases and separately labeled synthetic guards."""

import argparse
import runpy
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from finpanel import facts, filings, metrics
from finpanel.models import RawResponse
from finpanel.sec.companyfacts import parse_companyfacts
from finpanel.sec.submissions import parse_submissions
from finpanel.serialization import dumps, loads

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "derived_quarters.json"
FrozenValidation = runpy.run_path(str(ROOT / "examples" / "validate_canonical.py"))[
    "FrozenValidation"
]


class DerivedValidation(FrozenValidation):
    def run_derived(self, case):
        # Reuse the existing, explicitly recent-only four-issuer snapshot loader.
        self.run_case(
            {
                "issuer": case["issuer"],
                "metric": case["metric"],
                "as_of": case["as_of"],
                "query": {"fiscal_year": case["fiscal_year"], "period": "FY"},
            }
        )
        report = self.reports[(case["issuer"], case["metric"], case["as_of"])]
        result = metrics.derive_from_candidates(
            report,
            fiscal_year=case["fiscal_year"],
            quarter=case["quarter"],
            revision_policy=case["revision_policy"],
        )
        return result, report

    def check_derived(self, case, result, report):
        errors = []
        data = self.raw[f"{case['issuer']}_companyfacts.json"]
        evidence = [*case["minuend_sources"], *case["subtrahend_sources"]]
        if "reported_source" in case:
            evidence.append(case["reported_source"])
        for e in evidence:
            row = data
            for part in e["pointer"].split("/")[1:]:
                row = row[int(part)] if isinstance(row, list) else row[part]
            if (row["val"], row["accn"], row.get("start"), row["end"]) != (
                e["value"],
                e["accession"],
                e["start"],
                e["end"],
            ):
                errors.append("raw_source_mismatch")
        if (result.status, result.value) != (case["expected_status"], case["expected_value"]):
            errors.append(f"unexpected_result:{result.status}:{result.value}:{result.reasons}")
        if result.status == "eligible":
            for label in ("minuend", "subtrahend"):
                operand = getattr(result, label)
                actual = sorted(
                    (
                        c.mapping.concept,
                        c.observation.fact.observation.accession_number,
                        c.observation.fact.observation.provenance.pointer,
                    )
                    for c in operand.selected
                )
                expected = sorted(
                    (e["concept"], e["accession"], e["pointer"]) for e in case[f"{label}_sources"]
                )
                if actual != expected:
                    errors.append(f"{label}_selection_mismatch")
            if result.value + result.subtrahend.value != result.minuend.value:
                errors.append("arithmetic_identity_mismatch")
            p = result.target_interval
            if {"start": p.start.isoformat(), "end": p.end.isoformat()} != case["target_interval"]:
                errors.append("target_interval_mismatch")
            if result.source_type != "derived" or result.unit != "USD":
                errors.append("source_type_or_unit_mismatch")
        elif result.value is not None:
            errors.append("failed_derivation_has_scalar")
        if "expected_comparison" in case:
            comparison = metrics.compare_quarter_candidates(
                report,
                fiscal_year=case["fiscal_year"],
                quarter=case["quarter"],
                revision_policy=case["revision_policy"],
            )
            if comparison.status != case["expected_comparison"]:
                errors.append("comparison_status_mismatch")
            if case["expected_comparison"] == "equal":
                e = case["reported_source"]
                actual = [
                    (
                        c.observation.fact.observation.provenance.pointer,
                        c.observation.fact.observation.accession_number,
                    )
                    for c in comparison.reported.selected
                ]
                if comparison.difference != 0 or actual != [(e["pointer"], e["accession"])]:
                    errors.append("reported_comparison_evidence_mismatch")
        return errors


def _synthetic_report(concept):
    rows, accessions, ends = [], [], []
    for i, (fp, end, value) in enumerate(
        [("Q1", "2021-03-31", 100), ("Q2", "2021-06-30", 250), ("FY", "2021-12-31", 600)], 1
    ):
        accession = f"0000000001-22-{i:06d}"
        rows.append(
            {
                "start": "2021-01-01",
                "end": end,
                "val": value,
                "accn": accession,
                "fy": 2021,
                "fp": fp,
                "form": "10-K" if fp == "FY" else "10-Q",
                "filed": "2022-02-01",
            }
        )
        accessions.append(accession)
        ends.append(end)
    source = RawResponse(
        "https://fixture.invalid/derived-facts",
        dumps({"cik": 1, "facts": {"us-gaap": {concept: {"units": {"USD": rows}}}}}).encode(),
        "2026-01-01",
    )
    parent = RawResponse(
        "https://fixture.invalid/derived-submissions",
        dumps(
            {
                "cik": 1,
                "filings": {
                    "recent": {
                        "accessionNumber": accessions,
                        "reportDate": ends,
                        "form": ["10-Q", "10-Q", "10-K"],
                        "filingDate": ["2022-02-01"] * 3,
                        "acceptanceDateTime": ["2022-02-01T15:00:00Z"] * 3,
                    }
                },
            }
        ).encode(),
        "2026-01-01",
    )
    events = {
        f.accession_number: f
        for f in filings._merge("0000000001", list(parse_submissions(parent).records), [])
    }
    linked = tuple(
        facts.LinkedFact(
            o,
            o.observation_id,
            o.context,
            events[o.accession_number],
            events[o.accession_number].availability,
            (),
        )
        for o in parse_companyfacts(source).records
    )
    inspections = tuple(
        facts.FactInspection(
            "0000000001", m.concept, linked if m.concept == concept else (), (), (), (), (), ()
        )
        for m in metrics.REGISTRY["revenue"].mappings
    )
    return metrics.from_inspections(
        1, "revenue", as_of="2024-01-01T00:00:00Z", inspections=inspections
    )


def synthetic_guard(case_id):
    report = _synthetic_report("Revenues")
    a = metrics.resolve_candidates(report, fiscal_year=2021, period="YTD-Q2")
    b = metrics.resolve_candidates(report, fiscal_year=2021, period="Q1")
    if case_id == "cross-concept":
        b = metrics.resolve_candidates(
            _synthetic_report("SalesRevenueNet"), fiscal_year=2021, period="Q1"
        )
    elif case_id == "cross-unit":
        b = replace(b, unit="EUR")
    elif case_id == "interval-start":
        b = replace(
            b, represented_period=replace(b.represented_period, start=a.represented_period.end)
        )
    else:
        raise ValueError("Unknown synthetic guard")
    return metrics.derive_operands(a, b, fiscal_year=2021, quarter="Q2")


def validate(cache_dir):
    suite = DerivedValidation(cache_dir)
    golden = loads(GOLDEN.read_bytes())
    counts, failures = Counter(), []
    for case in golden["authentic_cases"]:
        result, report = suite.run_derived(case)
        errors = suite.check_derived(case, result, report)
        if errors:
            failures.append({"id": case["id"], "errors": errors})
        else:
            counts[result.status] += 1
    for case in golden["synthetic_guards"]:
        result = synthetic_guard(case["id"])
        if (
            result.status != case["expected_status"]
            or case["expected_reason"] not in result.reasons
        ):
            failures.append({"id": case["id"], "errors": ["synthetic_guard_mismatch"]})
        else:
            counts[result.status] += 1
    return {
        "title": "Derived-quarter validation",
        "issuers": 4,
        "metrics": 3,
        "golden_cases": len(golden["authentic_cases"]) + len(golden["synthetic_guards"]),
        "authentic_cases": len(golden["authentic_cases"]),
        "synthetic_guards": len(golden["synthetic_guards"]),
        "correctly_derived_expected_cases": counts["eligible"],
        "expected_conflicts": counts["conflicted"],
        "expected_rejections": counts["ineligible"] + counts["insufficient_evidence"],
        "matched_statuses": dict(sorted(counts.items())),
        "unexpected_mismatches": len(failures),
        "failures": failures,
        "scope": (
            "Frozen recent filings, four US-GAAP issuers; identities prove arithmetic only, "
            "not accounting correctness"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="finpanel-derived-") as temp:
        result = validate(Path(temp))
    encoded = dumps(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")
    return int(bool(result["unexpected_mismatches"]))


if __name__ == "__main__":
    raise SystemExit(main())
