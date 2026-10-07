"""Small frozen original-evidence population, not a market-wide accuracy estimate."""

import argparse
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from finpanel import xbrl
from finpanel.cache import FileCache
from finpanel.models import RawResponse
from finpanel.sec import parse_companyfacts, parse_submissions
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps, loads

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-10-08T00:00:00Z"


def seed_cache(cache):
    for folder in (ROOT / "tests/fixtures/sec", ROOT / "tests/fixtures/xbrl"):
        manifest = loads((folder / "manifest.json").read_bytes())
        for name, meta in manifest["files"].items():
            raw = RawResponse(
                meta["source_url"],
                (folder / name).read_bytes(),
                meta["retrieved_at"],
                raw_format=meta.get("raw_format", "json"),
            )
            if raw.sha256 != meta["sha256"]:
                raise ValueError("Frozen artifact hash mismatch: " + name)
            cache.put(raw)


class EvidenceValidation:
    def __init__(self, cache):
        seed_cache(cache)
        self.client = SECClient(cache=cache, offline=True)
        self.filings = {}
        self.observations = {}
        self.instances = {}
        manifest = loads((ROOT / "tests/fixtures/xbrl/manifest.json").read_bytes())
        for meta in manifest["files"].values():
            cik = meta["cik"]
            if cik not in self.filings:
                self.filings[cik] = parse_submissions(self.client.submissions(cik)).records
                self.observations[cik] = parse_companyfacts(self.client.companyfacts(cik)).records
            if meta["accession"] not in self.instances:
                f = next(f for f in self.filings[cik] if f.accession_number == meta["accession"])
                _, self.instances[meta["accession"]] = xbrl.inspect_filing(f, client=self.client)

    def run_case(self, case):
        observations = [
            o
            for o in self.observations[case["cik"]]
            if o.accession_number == case["accession"]
            and o.concept == case["concept"]
            and o.unit == "USD"
            and str(o.period_start) == str(case["start"])
            and str(o.period_end) == case["end"]
        ]
        if len(observations) != 1:
            raise ValueError("Golden does not identify exactly one Company Facts observation")
        observation = observations[0]
        v = xbrl.verify_fact(
            observation,
            instances=self.instances.get(case["accession"], ()),
            as_of=case.get("as_of", CUTOFF),
        )
        errors = []
        if observation.value != case["value"]:
            errors.append("companyfacts_value")
        if v.state != case["state"]:
            errors.append("verification_state:" + v.state)
        contexts = sorted({d.context.context_id for d in v.matches})
        if contexts != sorted(case["contexts"]):
            errors.append("original_contexts")
        if any(d.fact.numeric.decimals != "-6" for d in v.matches):
            errors.append("decimals")
        return v, errors


def benchmark(cache):
    validation = EvidenceValidation(cache)
    cases = loads((ROOT / "tests/golden/xbrl_evidence.json").read_bytes())["cases"]
    states = Counter(
        {
            key: 0
            for key in (
                "verified_unique",
                "verified_multiple_equivalent",
                "ambiguous_match",
                "source_mismatch",
                "instance_unavailable",
                "unsupported",
            )
        }
    )
    dimensioned = undimensioned = 0
    rows = []
    try:
        for case in cases:
            v, errors = validation.run_case(case)
            states[v.state] += 1
            dimensioned += any(d.context.dimensions for d in v.matches)
            undimensioned += any(not d.context.dimensions for d in v.matches)
            rows.append(
                {
                    "id": case["id"],
                    "state": v.state,
                    "errors": errors,
                    "companyfacts_source": v.observation.provenance,
                    "original_sources": [d.fact.provenance for d in v.matches],
                }
            )
    finally:
        validation.client.close()
    return {
        "population": "Manually selected USD observations in five frozen 2024 filings; "
        "one intentionally unavailable accession and one historical retrieval boundary. "
        "No market-wide accuracy claim; dimensioned and undimensioned counts may overlap.",
        "issuers": ["AAPL", "MSFT", "NVDA", "WMT"],
        "filings": len(validation.instances),
        "original_instance_files": sum(len(v) for v in validation.instances.values()),
        "facts_checked": len(cases),
        "states": dict(sorted(states.items())),
        "dimensioned_cases": dimensioned,
        "undimensioned_cases": undimensioned,
        "unexpected_mismatches": sum(bool(r["errors"]) for r in rows),
        "cases": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory() as folder:
        result = benchmark(FileCache(folder))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(result))
    print(dumps({k: v for k, v in result.items() if k != "cases"}))
    raise SystemExit(bool(result["unexpected_mismatches"]))
