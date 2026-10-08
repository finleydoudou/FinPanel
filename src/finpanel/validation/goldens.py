"""Literal SEC-source expectations and independent arithmetic, separate from coverage."""

from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal, localcontext
from pathlib import Path

from finpanel import panel
from finpanel._reuse import evaluation_reuse
from finpanel.errors import ValidationError
from finpanel.serialization import dumps, loads
from finpanel.snapshots.store import digest
from finpanel.validation.invariants import check_panel


def audit_sources(case, raw_by_hash):
    """Verify the ledger's literals and formula directly against original raw JSON."""
    errors = []
    values = []
    all_sources = case["sources"] + case.get("blocking_sources", [])
    for source in all_sources:
        raw = raw_by_hash[source["sha256"]]
        for part in source["pointer"].split("/")[1:]:
            part = part.replace("~1", "/").replace("~0", "~")
            raw = raw[int(part)] if isinstance(raw, list) else raw[part]
        if (raw["val"], raw.get("accn"), raw.get("start"), raw["end"]) != (
            source["value"],
            source["accession"],
            source["start"],
            source["end"],
        ):
            errors.append("golden_raw_source_mismatch")
        values.append(raw["val"])
    values = values[: len(case["sources"])]
    if case.get("absence_proof"):
        proof = case["absence_proof"]
        from datetime import date

        raw = raw_by_hash[proof["source_sha256"]]
        for obs in raw["facts"]["us-gaap"][proof["concept"]]["units"]["USD"]:
            if (
                obs.get("fp") == proof["fp"]
                and obs.get("fy") == proof["fiscal_year"]
                and obs.get("filed", "9999") <= proof["filed_through"]
                and obs.get("start")
                and (date.fromisoformat(obs["end"]) - date.fromisoformat(obs["start"])).days
                >= proof["minimum_duration_days"]
            ):
                errors.append("golden_absence_proof_failed")
    if case["formula"] == "difference":
        left, right = case["operand_counts"]
        if (
            len(values) != left + right
            or len(set(values[:left])) != 1
            or len(set(values[left:])) != 1
        ):
            errors.append("ambiguous_golden_operands")
        else:
            with localcontext() as ctx:
                ctx.prec = max(len(str(v)) for v in values) + 40
                expected = Decimal(values[0]) - Decimal(values[left])
                if expected != case.get("independent_arithmetic_value", case["expected_value"]):
                    errors.append("golden_arithmetic_mismatch")
    elif case["expected_state"] == "resolved_reported":
        if not values or any(v != case["expected_value"] for v in values):
            errors.append("golden_reported_literal_mismatch")
    return errors


def validate_goldens(store, snapshot_id, golden_file, *, output=None, reuse=True):
    ledger = loads(Path(golden_file).read_bytes())
    if ledger["format"] != "finpanel-independent-goldens-v1":
        raise ValidationError("Unknown golden schema")
    ids = [c["id"] for c in ledger["cases"]]
    if len(ids) != len(set(ids)):
        raise ValidationError("Duplicate golden case IDs")
    snapshot = store.select(snapshot_id=snapshot_id)
    artifacts = {
        a["sha256"]: a
        for a in snapshot.manifest["artifacts"]
        if a["source_family"] == "companyfacts"
    }
    groups = defaultdict(list)
    for c in ledger["cases"]:
        key = (
            c["cik"],
            c["as_of"],
            c["revision_policy"],
            c["source_policy"],
            c["source_verification"],
        )
        groups[key].append(c)
    findings = []
    checks = 0
    invariant_failures = []
    receipts = []
    seen_issuers = set()
    current_cik = None
    raw_by_hash = {}
    for key, cases in sorted(groups.items()):
        cik, cutoff, revision, source, verification = key
        if current_cik != cik:
            raw_by_hash = {
                h: store.raw(store._artifact(a)).json()
                for h, a in artifacts.items()
                if a["cik"] == cik
            }
            current_cik = cik
        seen_issuers.add(cik)
        ends = {
            (c["fiscal_year"], c["period"], c["instant_end"]) for c in cases if c["instant_end"]
        }
        req = panel.PanelRequest(
            entities=(cik,),
            metrics=tuple({c["metric"] for c in cases}),
            fiscal_years=tuple({c["fiscal_year"] for c in cases}),
            periods=tuple({c["period"] for c in cases}),
            as_of=(cutoff,),
            revision_policy=revision,
            source_policy=source,
            source_verification=verification,
            snapshot_id=snapshot_id,
            period_ends=tuple(panel.PeriodEnd(cik, y, p, e) for y, p, e in ends),
        )
        with evaluation_reuse(enabled=reuse):
            result = panel.build(req, store=store)
        invariant = check_panel(result, store)
        checks += invariant["checks"]
        invariant_failures.extend(invariant["failures"])
        rows = {(r.fiscal_year, r.period, r.metric): r for r in result.rows}
        for c in cases:
            errors = audit_sources(c, raw_by_hash)
            r = rows[c["fiscal_year"], c["period"], c["metric"]]
            if (r.state, r.value) != (c["expected_state"], c["expected_value"]):
                errors.append("golden_result_mismatch")
            findings.append(
                dict(
                    id=c["id"],
                    cik=cik,
                    expected_state=c["expected_state"],
                    expected_value=c["expected_value"],
                    actual_state=r.state,
                    actual_value=r.value,
                    reasons=r.reasons,
                    passed=not errors,
                    errors=errors,
                )
            )
        receipts.append(dict(query=asdict(req), receipt_id=result.receipt.receipt_id))
        del result
    report = {
        "format": "finpanel-golden-validation-v1",
        "golden_hash": digest(ledger),
        "snapshot_id": snapshot_id,
        "issuer_count": len(seen_issuers),
        "case_count": len(findings),
        "matched": sum(f["passed"] for f in findings),
        "unexpected_mismatches": sum(not f["passed"] for f in findings) + len(invariant_failures),
        "invariant_checks": checks,
        "invariant_failures": invariant_failures,
        "findings": findings,
        "receipts": receipts,
    }
    if output:
        Path(output).write_text(dumps(report))
    return report
