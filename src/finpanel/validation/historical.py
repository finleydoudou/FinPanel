"""Experimental historical audits; diagnostics never select or change a financial value."""

from dataclasses import asdict
from datetime import date

from finpanel import asof, revisions
from finpanel.errors import ValidationError
from finpanel.models.asof import EvidenceView
from finpanel.sec.client import SECClient
from finpanel.snapshots import EvidenceStore
from finpanel.snapshots.pipeline import _PinnedCache

TRANSITION_FORMS = frozenset({"10-KT", "10-KT/A", "10-QT", "10-QT/A"})


def bounded_view(
    store: EvidenceStore, snapshot_id: str, cik: str, concept: str, cutoff: str
) -> EvidenceView:
    """Read one exact concept from one immutable snapshot, with no live fallback."""
    snapshot = store.select(snapshot_id=snapshot_id)
    with SECClient(cache=_PinnedCache(store, snapshot), offline=True) as client:
        return asof.view(cik, cutoff, concept=concept, taxonomy="us-gaap", client=client)


def calendar_diagnostics(view: EvidenceView) -> tuple[dict, ...]:
    """Describe admitted contexts without imposing a fiscal label on transition periods.

    Current FYE is deliberately excluded by the evidence boundary. An observed
    month/day movement is not, by itself, proof that the issuer changed its policy.
    """
    if view.mode != "as_of":
        raise ValidationError("Calendar audit requires a bounded as-of view")
    findings = []
    for row in view.records:
        obs = row.fact.observation
        if not row.eligibility.eligible_as_of or row.eligibility.as_of != view.as_of:
            raise ValidationError("Calendar audit contains inadmissible evidence")
        codes = []
        days = row.period.duration_days
        if obs.form in TRANSITION_FORMS:
            codes.append("explicit_transition_filing")
            if days is not None and days < 350:
                codes.append("shortened_transition_period")
            elif days is not None and days > 378:
                codes.append("extended_transition_period")
        if days is not None and row.period.identity.label is None:
            codes.append("insufficient_calendar_anchors")
            if obs.fiscal_period in {"Q1", "Q2", "Q3"}:
                codes.append("uncertain_quarter_boundary")
        if row.period.kind == "annual":
            if days in {364, 371}:
                codes.append("52_week_year" if days == 364 else "53_week_year")
            if obs.period_end.strftime("%m%d") != "1231":
                codes.append("non_calendar_year")
        if obs.period_start and obs.period_end:
            for year in range(obs.period_start.year, obs.period_end.year + 1):
                try:
                    leap = date(year, 2, 29)
                except ValueError:
                    continue
                if obs.period_start <= leap <= obs.period_end:
                    codes.append("includes_leap_day")
        if codes:
            findings.append(
                dict(
                    observation_id=obs.observation_id,
                    codes=sorted(set(codes)),
                    source=asdict(obs.provenance),
                    accession=obs.accession_number,
                    as_of=view.as_of.isoformat(),
                    classification=row.period.kind,
                    fiscal_label=row.period.identity.label,
                    duration_days=days,
                )
            )
    if view.calendar:
        windows = sorted(view.calendar.years, key=lambda w: (w.start, w.end, w.fiscal_year))
        for previous, current in zip(windows, windows[1:], strict=False):
            if previous.end < current.start and previous.end.strftime(
                "%m%d"
            ) != current.end.strftime("%m%d"):
                findings.append(
                    dict(
                        codes=["observed_fiscal_boundary_movement"],
                        previous_end=previous.end.isoformat(),
                        current_end=current.end.isoformat(),
                        as_of=view.as_of.isoformat(),
                        evidence=[asdict(e) for e in (*previous.evidence, *current.evidence)],
                        interpretation=(
                            "Observed windows only; cause and intervening calendar not inferred"
                        ),
                    )
                )
    return tuple(findings)


def revision_observations(view: EvidenceView) -> tuple[dict, ...]:
    """Describe temporal evidence patterns, never assert formal accounting causality.

    An amendment identifies a filing form, not whether its financials were restated.
    Formal-restatement claims require separately audited original narrative evidence.
    """
    history = revisions.analyze(view, policy="all_available")
    output = []
    for group in history.groups:
        candidates = group.candidates
        values = {c.observation.fact.observation.value for c in candidates}
        codes = []
        if any(c.is_amendment for c in candidates):
            codes.append("amendment_filing")
        if len(candidates) > 1 and len(values) == 1:
            codes.append("repeated_unchanged_observation")
        if len(values) > 1:
            codes.append("unexplained_value_change")
            if any(c.is_comparative for c in candidates):
                codes.append("later_comparative_revision")
        if not codes:
            codes.append("unknown")
        output.append(
            dict(
                identity=group.identity,
                categories=codes,
                causal_claim="none",
                as_of=view.as_of.isoformat(),
                candidates=[
                    dict(
                        value=c.observation.fact.observation.value,
                        accession=c.observation.fact.observation.accession_number,
                        source=asdict(c.observation.fact.observation.provenance),
                        availability=asdict(c.observation.eligibility),
                    )
                    for c in candidates
                ],
            )
        )
    return tuple(output)


def current_fye_comparison(view: EvidenceView, current_fye: str, source: dict) -> dict:
    """Retrospective audit annotation only; never admitted as historical evidence.

    The caller must identify the captured submissions response and its root pointer.
    A mismatch may reflect a 52/53-week boundary, not a policy change.
    """
    if view.mode != "as_of":
        raise ValidationError("Comparison requires a bounded as-of view")
    if len(current_fye) != 4 or not current_fye.isdigit():
        raise ValidationError("Current FYE must be MMDD")
    try:
        date(2000, int(current_fye[:2]), int(current_fye[2:]))
    except ValueError as exc:
        raise ValidationError("Invalid current FYE") from exc
    if not all(source.get(k) for k in ("source_url", "response_sha256", "pointer")):
        raise ValidationError("Current metadata requires source provenance")
    return {
        "mode": "retrospective_metadata_comparison",
        "eligible_historical_anchor": False,
        "as_of": view.as_of.isoformat(),
        "current_fye": current_fye,
        "source": source,
        "mismatched_observed_windows": [
            {
                "code": "historical_current_fye_mismatch",
                "start": w.start,
                "end": w.end,
                "evidence": [asdict(e) for e in w.evidence],
            }
            for w in (view.calendar.years if view.calendar else ())
            if w.end.strftime("%m%d") != current_fye
        ],
    }
