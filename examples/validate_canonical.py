"""Deterministic, offline four-issuer golden validation; no resolver-generated expectations."""

import argparse
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from finpanel import filings, metrics
from finpanel.cache import FileCache
from finpanel.models import ParseIssue, RawResponse
from finpanel.models.timeline import FilingTimeline
from finpanel.sec.client import SECClient
from finpanel.sec.submissions import discover_historical_submissions, parse_submissions
from finpanel.serialization import dumps, loads

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "canonical.json"


class FrozenValidation:
    """Use intact recent-submission snapshots; explicitly disclose unloaded history."""

    def __init__(self, cache_dir: Path):
        self.folder = ROOT / "tests" / "fixtures" / "sec"
        self.manifest = loads((self.folder / "manifest.json").read_bytes())["files"]
        self.cache = FileCache(cache_dir)
        self.timelines = {}
        self.reports = {}
        self.raw = {}
        for name, meta in self.manifest.items():
            source = RawResponse(
                meta["source_url"], (self.folder / name).read_bytes(), meta["retrieved_at"]
            )
            if source.sha256 != meta["sha256"]:
                raise ValueError(f"Fixture digest mismatch: {name}")
            self.raw[name] = source.json()
            self.cache.put(source)
            if name.endswith("_submissions.json"):
                parsed = parse_submissions(source)
                refs = discover_historical_submissions(source)
                issues = [
                    *parsed.issues,
                    ParseIssue(
                        "golden_recent_only",
                        "Benchmark uses recent snapshot; referenced history is unloaded",
                        source.provenance("/filings/files"),
                        parsed.metadata["history_files"],
                    ),
                ]
                records = filings._merge(meta["cik"], list(parsed.records), issues)
                self.timelines[name.split("_")[0]] = FilingTimeline(
                    meta["cik"],
                    records,
                    tuple(issues),
                    (parsed.source,),
                    refs.records,
                    (),
                )

    def run_case(self, case):
        key = (case["issuer"], case["metric"], case["as_of"])
        if key not in self.reports:
            timeline = self.timelines[case["issuer"]]
            with SECClient(cache=self.cache, offline=True) as client:
                self.reports[key] = metrics.candidates(
                    timeline.cik,
                    case["metric"],
                    as_of=case["as_of"],
                    client=client,
                    filing_timeline=timeline,
                )
        return metrics.resolve_candidates(self.reports[key], **case["query"])

    def check(self, case, result):
        errors = []
        # Independent raw-source audit before comparing resolver output.
        for evidence in case["expected_sources"]:
            row = self.raw[evidence["file"]]
            for part in evidence["pointer"].split("/")[1:]:
                row = row[int(part)] if isinstance(row, list) else row[part]
            if (row["val"], row["accn"], row.get("start"), row["end"]) != (
                evidence["value"],
                evidence["accession"],
                case["represented_period"]["start"],
                case["represented_period"]["end"],
            ):
                errors.append("raw_evidence_mismatch")
        if (result.state, result.value) != (case["expected_state"], case["expected_value"]):
            errors.append(f"result:{result.state}:{result.value}")
        if result.state == "resolved":
            actual = sorted(
                (
                    c.mapping.concept,
                    c.observation.fact.observation.accession_number,
                    c.observation.fact.observation.provenance.pointer,
                )
                for c in result.selected
            )
            expected = sorted(
                (e["concept"], e["accession"], e["pointer"]) for e in case["expected_sources"]
            )
            if actual != expected:
                errors.append("selected_source_mismatch")
            p = result.represented_period
            if {
                "start": p.start.isoformat() if p.start else None,
                "end": p.end.isoformat(),
            } != case["represented_period"]:
                errors.append("represented_period_mismatch")
            if result.unit != "USD":
                errors.append("unit_mismatch")
        elif result.value is not None or result.selected:
            errors.append("unexpected_scalar_or_selection")
        return errors


def validate(cache_dir: Path) -> dict:
    suite = FrozenValidation(cache_dir)
    cases = loads(GOLDEN.read_bytes())["cases"]
    failures = []
    counts = Counter()
    for case in cases:
        result = suite.run_case(case)
        errors = suite.check(case, result)
        if errors:
            failures.append({"id": case["id"], "errors": errors})
        else:
            counts[case["expected_state"]] += 1
    return {
        "title": "Canonical fundamentals validation",
        "issuers": 4,
        "metrics": 6,
        "golden_cases": len(cases),
        "matched_expected_states": dict(sorted(counts.items())),
        "unexpected_mismatches": len(failures),
        "failures": failures,
        "scope": (
            "Four frozen US-GAAP issuers; recent filings only; not a population accuracy claim"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="finpanel-golden-") as temp:
        report = validate(Path(temp))
    encoded = dumps(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")
    return int(bool(report["unexpected_mismatches"]))


if __name__ == "__main__":
    raise SystemExit(main())
