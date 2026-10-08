"""Sequential issuer batches retain every cell while bounding live evidence memory."""

import gc
import platform
import subprocess
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from finpanel import metrics, panel
from finpanel._reuse import evaluation_reuse
from finpanel.errors import FinPanelError, ValidationError
from finpanel.panel.engine import row_record
from finpanel.panel.models import STATES
from finpanel.serialization import dumps
from finpanel.snapshots.pipeline import software_identity
from finpanel.snapshots.store import EvidenceStore, digest
from finpanel.validation.invariants import check_panel
from finpanel.validation.taxonomy import classify
from finpanel.validation.universe import selection, universe, universe_hash


class MeasuredStore(EvidenceStore):
    """Read-through filesystem store with counters; integrity checks remain enabled."""

    def __init__(self, root):
        super().__init__(root)
        self.snapshot_loads = 0
        self.object_reads = 0

    def load(self, snapshot_id):
        self.snapshot_loads += 1
        return super().load(snapshot_id)

    def raw(self, artifact):
        self.object_reads += 1
        return super().raw(artifact)


@dataclass(frozen=True)
class BenchmarkConfig:
    fiscal_years: tuple[int, ...] = (2023, 2024)
    periods: tuple[str, ...] = ("FY", "Q1", "Q2", "Q3", "Q4")
    as_of: tuple[str, ...] = ("2024-08-15T00:00:00Z", "2025-04-01T00:00:00Z")
    revision_policies: tuple[str, ...] = ("first_reported", "latest_available")
    timeline_scope: str = "complete"
    reuse: bool = True
    replay: bool = True
    source_verification: bool = True


def explicit_ends(store, snapshot_id, cik, years, periods):
    """Benchmark query preparation from raw reporting labels, never resolver output.

    These are explicit requested dates, not a guarantee of fiscal interpretation.
    Only unique end dates associated with the issuer's own FY/fp filing are used.
    Ambiguous associations stay absent and therefore produce unsupported instant rows.
    The query dates are recorded in every panel receipt.
    """
    snapshot = store.load(snapshot_id)
    artifacts = [
        a
        for a in snapshot.manifest["artifacts"]
        if a["cik"] == cik and a["source_family"] == "companyfacts"
    ]
    if not artifacts:
        return ()
    raw = store.raw(store._artifact(artifacts[0])).json()
    found = {}
    for observation in (
        raw.get("facts", {}).get("us-gaap", {}).get("Assets", {}).get("units", {}).get("USD", [])
    ):
        year = observation.get("fy")
        period = observation.get("fp")
        end = observation.get("end")
        if year not in years or period not in {"FY", "Q1", "Q2", "Q3"} or not end:
            continue
        # The most recent end in each fy/fp bucket describes the reporting period;
        # earlier ends are comparative balances. This chooses inputs only.
        key = (year, period)
        found[key] = max(found.get(key, end), end)
    return tuple(
        panel.PeriodEnd(cik, y, p, found[y, "FY" if p == "Q4" else p])
        for y in years
        for p in periods
        if (y, "FY" if p == "Q4" else p) in found
    )


def peak_memory():
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value / (1024**2 if platform.system() == "Darwin" else 1024)
    except ImportError:
        return None


def run(store, snapshot_id, destination, *, manifest=None, config=None, tier="B", limit=None):
    """Offline only. New destination required; publish report after all issuer batches."""
    started = time.perf_counter()
    store = MeasuredStore(store.root)
    data = universe() if manifest is None else manifest
    issuers = selection(data, tier=tier, limit=limit)
    config = config or BenchmarkConfig()
    snapshot = store.select(snapshot_id=snapshot_id)
    out = Path(destination)
    if out.exists():
        raise ValidationError("Benchmark output must be a new directory")
    out.mkdir(parents=True)
    states = Counter()
    categories = Counter()
    kinds = Counter()
    findings = []
    batch_hashes = []
    receipts = []
    cells = []
    performance = []
    invariant_count = 0
    replays = 0
    reuse_stats = []
    failures = []
    verification_states = Counter()
    for issuer in issuers:
        cik = issuer["cik"]
        ends = explicit_ends(store, snapshot_id, cik, config.fiscal_years, config.periods)
        with evaluation_reuse(enabled=config.reuse) as reuse:
            for policy in config.revision_policies:
                request = panel.PanelRequest(
                    entities=(cik,),
                    metrics=tuple(metrics.REGISTRY),
                    fiscal_years=config.fiscal_years,
                    periods=config.periods,
                    as_of=config.as_of,
                    revision_policy=policy,
                    snapshot_id=snapshot_id,
                    period_ends=ends,
                    timeline_scope=config.timeline_scope,
                )
                try:
                    result = panel.build(request, store=store)
                    checks = check_panel(result, store)
                    invariant_count += checks["checks"]
                    failures.extend(checks["failures"])
                    states.update(r.state for r in result.rows)
                    for row in result.rows:
                        finding = classify(
                            row, result.provenance[row.row_id], result.results.get(row.row_id)
                        )
                        kinds[finding["kind"]] += 1
                        categories.update(finding["categories"])
                        record = dict(
                            cik=cik,
                            row_id=row.row_id,
                            revision_policy=policy,
                            state=row.state,
                            **finding,
                        )
                        if finding["kind"] != "resolved":
                            findings.append(record)
                        if finding["kind"] == "unexpected_failure":
                            failures.append(record)
                        cells.append(row_record(row))
                    folder = out / cik / policy
                    folder.mkdir(parents=True)
                    panel.export(result, folder / "panel.parquet")
                    (folder / "receipt.json").write_text(dumps(result.receipt))
                    receipts.append(
                        {"cik": cik, "policy": policy, "receipt_id": result.receipt.receipt_id}
                    )
                    batch_hashes.append(result.receipt.semantic["row_hash"])
                    performance.append(result.performance)
                    if config.replay:
                        replayed = panel.reproduce(result.receipt, store=store)
                        if replayed.receipt.receipt_id != result.receipt.receipt_id:
                            failures.append(
                                {
                                    "cik": cik,
                                    "category": "internal_invariant_violation",
                                    "code": "replay_mismatch",
                                }
                            )
                        else:
                            replays += 1
                        del replayed
                    del result
                except Exception as exc:
                    failures.append(
                        {
                            "cik": cik,
                            "policy": policy,
                            "category": "parser_source_defect"
                            if isinstance(exc, FinPanelError)
                            else "internal_invariant_violation",
                            "error_type": type(exc).__name__,
                        }
                    )
            if config.source_verification:
                # Evidence-vintage check is separate from historical financial cutoffs.
                verify = panel.build(
                    panel.PanelRequest(
                        entities=(cik,),
                        metrics=("assets",),
                        fiscal_years=config.fiscal_years,
                        periods=("FY",),
                        as_of=(snapshot.manifest["captured_through"],),
                        snapshot_id=snapshot_id,
                        source_verification="best_effort",
                        revision_policy="first_reported",
                        timeline_scope=config.timeline_scope,
                        period_ends=tuple(e for e in ends if e.period == "FY"),
                    ),
                    store=store,
                )
                source_checks = check_panel(verify, store)
                invariant_count += source_checks["checks"]
                failures.extend(source_checks["failures"])
                verification_states.update(r.verification_state for r in verify.rows)
                for row in verify.rows:
                    if "source_mismatch" in row.verification_state:
                        failures.append(
                            {
                                "cik": cik,
                                "row_id": row.row_id,
                                "category": "source_match_ambiguity",
                                "code": "cross_layer_source_mismatch",
                            }
                        )
                (out / cik / "source-verification.json").write_text(
                    dumps(
                        {
                            "rows": verify.rows,
                            "provenance": verify.provenance,
                            "receipt": verify.receipt,
                        }
                    )
                )
                del verify
        reuse_stats.append(reuse.statistics())
        gc.collect()
    report = {
        "format": "finpanel-broad-validation-v1",
        "universe_hash": universe_hash(data),
        "tier": tier,
        "issuer_count": len(issuers),
        "category_distribution": dict(sorted(Counter(i["category"] for i in issuers).items())),
        "fiscal_calendar_distribution": dict(
            sorted(Counter(i.get("fiscal_year_end") or "unknown" for i in issuers).items())
        ),
        "requested_cells": len(issuers)
        * len(config.revision_policies)
        * len(config.fiscal_years)
        * len(config.periods)
        * len(config.as_of)
        * len(metrics.REGISTRY),
        "observed_cells": len(cells),
        "states": {state: states[state] for state in sorted(STATES)},
        "findings_by_kind": dict(sorted(kinds.items())),
        "failure_categories": dict(sorted(categories.items())),
        "source_verification_states": dict(sorted(verification_states.items())),
        "source_verification_queries": sum(verification_states.values()),
        "source_verification_policy": (
            "best_effort at snapshot capture cutoff; separate from historical rows"
        ),
        "invariant_checks": invariant_count,
        "successful_replays": replays,
        "unexpected_mismatches": len(failures),
        "unexpected_findings": failures,
        "coverage_meaning": (
            "Scalar availability under these evidence and policy contracts; not accuracy"
        ),
        "golden_correctness": "Separate independent golden report required",
    }
    receipt = {
        "format": "finpanel-benchmark-receipt-v1",
        "universe_hash": universe_hash(data),
        "snapshot_id": snapshot_id,
        "query": asdict(config),
        "software": software_identity(),
        "batch_receipts": receipts,
        "semantic_dataset_hash": digest(cells),
        "batch_hashes": batch_hashes,
        "report_hash": digest(report),
        "environment": {"platform": platform.platform()},
        "source_manifest_hash": digest(snapshot.manifest),
    }
    try:
        receipt["git_head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        receipt["git_head"] = None
    measurement = {
        "wall_seconds": time.perf_counter() - started,
        "process_peak_rss_mib": peak_memory(),
        "candidate_builds": sum(p["candidate_builds"] for p in performance),
        "candidate_reuses": sum(p["candidate_reuses"] for p in performance),
        "raw_response_reuses": sum(p["raw_response_reuses"] for p in performance),
        "snapshot_loads": store.snapshot_loads,
        "snapshot_object_reads": store.object_reads,
        "reuse": reuse_stats,
        "source_parses": sum(s["builds"].get("companyfacts_parse", 0) for s in reuse_stats),
        "source_parse_hits": sum(s["hits"].get("companyfacts_parse", 0) for s in reuse_stats),
        "workers": 1,
        "issuer_batches": len(issuers),
    }
    for filename, value in [
        ("report.json", report),
        ("receipt.json", receipt),
        ("findings.json", findings),
        ("performance.json", measurement),
    ]:
        (out / filename).write_text(dumps(value))
    return report, receipt, measurement
