"""Stable validation findings: conservative abstention is not implementation failure."""

CATEGORIES = frozenset(
    {
        "unsupported_concept",
        "extension_only_reporting",
        "ambiguous_fiscal_period",
        "incomplete_filing_history",
        "missing_original_xbrl_instance",
        "source_match_ambiguity",
        "dimensioned_fact",
        "incompatible_revision_operands",
        "insufficient_cumulative_facts",
        "snapshot_evidence_gap",
        "unit_incompatibility",
        "conflicting_observations",
        "parser_source_defect",
        "internal_invariant_violation",
        "not_available_as_of",
        "unsupported_request",
        "unclassified_conservative_result",
        "acquisition_failure",
    }
)


def classify(row, evidence, canonical=None):
    """Do not infer issuer-wide extension use from a single missing metric."""
    if row.state.startswith("resolved_"):
        return {"kind": "resolved", "categories": []}
    canonical = getattr(canonical, "original", canonical)
    report = getattr(canonical, "candidates", None)
    if (
        row.state == "unavailable"
        and report is not None
        and not report.records
        and not report.rejected
    ):
        namespaces = {c.taxonomy for c in report.unmapped_concepts}
        category = (
            "extension_only_reporting"
            if namespaces - {"dei"} and "us-gaap" not in namespaces
            else "unsupported_concept"
        )
        return {"kind": "expected_conservatism", "categories": [category]}
    reasons = " ".join(row.reasons + row.conflicts).lower()
    categories = set()
    if evidence.get("error_type") or "integrity_failure" in reasons:
        if "missing_evidence" in reasons or "source_unavailable" in reasons:
            return {"kind": "evidence_gap", "categories": ["snapshot_evidence_gap"]}
        return {"kind": "unexpected_failure", "categories": ["parser_source_defect"]}
    rules = [
        ("unit", "unit_incompatibility"),
        ("dimensioned_arithmetic_not_supported", "dimensioned_fact"),
        ("ambiguous_period", "ambiguous_fiscal_period"),
        ("period_ambiguous", "ambiguous_fiscal_period"),
        ("unpaired_value_revision", "incompatible_revision_operands"),
        ("cumulative", "insufficient_cumulative_facts"),
        ("unknown_availability", "incomplete_filing_history"),
        ("unsupported_concept", "unsupported_concept"),
        ("source_verification", "missing_original_xbrl_instance"),
        ("source_match", "source_match_ambiguity"),
        ("explicit_instant_end", "unsupported_request"),
        ("requires_quarter", "unsupported_request"),
        ("no_eligible_reported", "not_available_as_of"),
    ]
    for token, category in rules:
        if token in reasons:
            categories.add(category)
    if row.state == "conflicted":
        categories.add("conflicting_observations")
    if row.state == "insufficient_evidence":
        categories.add("insufficient_cumulative_facts")
    if row.state == "ambiguous_period":
        categories.add("ambiguous_fiscal_period")
    if row.state == "unsupported" and not categories:
        categories.add("unsupported_concept")
    return {
        "kind": "expected_conservatism",
        "categories": sorted(categories or {"unclassified_conservative_result"}),
    }
