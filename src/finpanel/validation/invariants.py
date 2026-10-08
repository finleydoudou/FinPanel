"""Independent consistency assertions on resolved panel evidence, without choosing values."""

from decimal import Decimal, localcontext

from finpanel import metrics
from finpanel.panel.engine import _operands
from finpanel.serialization import loads


def check_panel(result, store):
    failures = []
    checks = 0
    raws = {}
    identities = {a["source_url"]: a for a in result.receipt.semantic["artifacts"]}
    snapshot = store.load(result.request.snapshot_id)
    artifacts = {a["source_url"]: a for a in snapshot.manifest["artifacts"]}

    def check(ok, row, code):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(
                {"row_id": row.row_id, "category": "internal_invariant_violation", "code": code}
            )

    for row in result.rows:
        check(row.snapshot_id == result.request.snapshot_id, row, "one_snapshot")
        check(
            row.value is None or row.state.startswith("resolved_"), row, "unresolved_has_no_scalar"
        )
        wrapped = result.results.get(row.row_id)
        original = getattr(wrapped, "original", wrapped)
        if original is None:
            continue
        check(row.value == getattr(wrapped, "value", None), row, "panel_canonical_value")
        derived = isinstance(original, metrics.QuarterDerivation)
        check(row.source_type == original.source_type, row, "reported_derived_distinction")
        if derived:
            check(metrics.REGISTRY[row.metric].context != "instant", row, "instant_not_derived")
            if row.value is not None:
                a, b = original.minuend, original.subtrahend
                left = {
                    (
                        c.observation.fact.observation.taxonomy,
                        c.observation.fact.observation.concept,
                        c.observation.fact.observation.unit,
                    )
                    for c in a.selected
                }
                right = {
                    (
                        c.observation.fact.observation.taxonomy,
                        c.observation.fact.observation.concept,
                        c.observation.fact.observation.unit,
                    )
                    for c in b.selected
                }
                check(left == right and len(left) == 1, row, "same_concept_and_unit")
                with localcontext() as ctx:
                    ctx.prec = max(len(str(a.value)), len(str(b.value))) + 40
                    check(
                        Decimal(row.value) == Decimal(a.value) - Decimal(b.value),
                        row,
                        "exact_operand_difference",
                    )
        for operand in _operands(original):
            check(operand.evidence_snapshot_id == row.snapshot_id, row, "operand_snapshot")
            for candidate in operand.selected:
                observation = candidate.observation
                fact = observation.fact.observation
                for eligibility in (observation.eligibility, *observation.supporting_evidence):
                    check(
                        eligibility.eligible_as_of and eligibility.as_of == row.as_of,
                        row,
                        "eligible_support_at_cutoff",
                    )
                    availability = eligibility.source_availability
                    if availability.timestamp:
                        check(availability.timestamp <= row.as_of, row, "no_future_evidence")
                source = fact.provenance
                check(
                    source.source_url in identities
                    and identities[source.source_url]["sha256"] == source.response_sha256,
                    row,
                    "source_hash_in_receipt",
                )
                if source.source_url not in raws:
                    raws[source.source_url] = loads(
                        store.raw(store._artifact(artifacts[source.source_url])).body
                    )
                raw = raws[source.source_url]
                try:
                    for part in source.pointer.split("/")[1:]:
                        part = part.replace("~1", "/").replace("~0", "~")
                        raw = raw[int(part)] if isinstance(raw, list) else raw[part]
                    check(
                        raw["val"] == fact.value and raw.get("accn") == fact.accession_number,
                        row,
                        "raw_to_canonical_exact",
                    )
                except (KeyError, IndexError, TypeError, ValueError):
                    check(False, row, "raw_pointer_unreadable")
    return {"checks": checks, "failures": failures}
