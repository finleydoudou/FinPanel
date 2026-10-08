"""Serial, resumable official-SEC acquisition into immutable WP4 evidence stores."""

from dataclasses import asdict
from pathlib import Path

from finpanel.cache.file import atomic_write
from finpanel.errors import FinPanelError, ValidationError
from finpanel.sec.client import RateLimiter, SECClient
from finpanel.sec.submissions import discover_historical_submissions
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore, SnapshotError
from finpanel.validation.universe import selection, universe, universe_hash


def acquire(destination, *, manifest=None, tier="B", limit=None, client=None, history=True):
    """One caller at a time; successful artifacts are reverified and reused on resume.

    Failed requests are recorded by category, never replaced with synthetic evidence.
    A checkpoint is operational metadata, not the immutable evidence contract. Each
    completion publishes a new immutable manifest. No parallel SEC requests are used.
    """
    destination = Path(destination)
    data = universe() if manifest is None else manifest
    issuers = selection(data, tier=tier, limit=limit)
    config = dict(universe_hash=universe_hash(data), tier=tier, limit=limit, history=history)
    path = destination / "acquisition.json"
    store = EvidenceStore(destination / "evidence")
    state = (
        loads(path.read_bytes())
        if path.exists()
        else dict(config=config, artifacts={}, failures={}, issuers={})
    )
    if state["config"] != config:
        raise ValidationError("Resume configuration differs; choose a separate corpus directory")
    for artifact in state["artifacts"].values():
        store.raw(store._artifact(artifact))  # Corruption is a hard failure, not a redownload.
    owned = client is None
    client = client or SECClient(
        cache_dir=destination / "cache", limiter=RateLimiter(2.0), max_retries=1
    )

    def checkpoint():
        atomic_write(path, dumps(state).encode())

    def capture(cik, endpoint, *args):
        key = "/".join((cik, endpoint, *args))
        if key in state["artifacts"]:
            return store.raw(store._artifact(state["artifacts"][key]))
        try:
            raw = getattr(client, endpoint)(cik, *args)
            artifact = store.capture(raw, source_family=endpoint, cik=cik, authenticity="authentic")
            state["artifacts"][key] = asdict(artifact)
            state["failures"].pop(key, None)
            checkpoint()
            return raw
        except SnapshotError:
            raise
        except FinPanelError as exc:
            state["failures"][key] = dict(
                category="acquisition_failure",
                error_type=type(exc).__name__,
                status_code=getattr(exc, "status", None),
            )
            checkpoint()
            return None

    try:
        for issuer in issuers:
            cik = issuer["cik"]
            submissions = capture(cik, "submissions")
            if submissions:
                info = submissions.json()
                if str(info.get("cik")).zfill(10) != cik:
                    raise ValidationError("SEC issuer identity mismatch")
                forms = info.get("filings", {}).get("recent", {}).get("form", [])
                state["issuers"][cik] = dict(
                    entity_name=info.get("name"),
                    fiscal_year_end=info.get("fiscalYearEnd"),
                    sic=info.get("sic"),
                    sic_description=info.get("sicDescription"),
                    has_10k="10-K" in forms,
                    has_20f="20-F" in forms,
                    source=submissions.provenance(""),
                )
                checkpoint()
                if history:
                    for reference in discover_historical_submissions(submissions).records:
                        capture(cik, "historical_submissions", reference.name)
            capture(cik, "companyfacts")
        if not state["artifacts"]:
            raise ValidationError("No authentic evidence acquired")
        required = [
            url
            for issuer in issuers
            for url in (
                f"https://data.sec.gov/submissions/CIK{issuer['cik']}.json",
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{issuer['cik']}.json",
            )
        ]
        snapshot = store.create(
            [store._artifact(a) for a in state["artifacts"].values()],
            scope="WP6 " + tier + " " + config["universe_hash"],
            required_urls=required,
            incompleteness=("Original XBRL not included by aggregate acquisition",)
            + (("Referenced history not requested",) if not history else ())
            + (("Acquisition failures recorded in checkpoint",) if state["failures"] else ()),
        )
        state["snapshot_id"] = snapshot.snapshot_id
        checkpoint()
        return state
    finally:
        if owned:
            client.close()


def acquire_originals(destination, *, manifest=None, fiscal_year=2023, client=None):
    """Acquire one declared original instance per Tier A issuer for an explicit year.

    Uses official directory/index discovery. Archive denials remain limitations;
    filenames are never guessed and alternate endpoints are not tried.
    """
    from finpanel import filings, xbrl
    from finpanel.validation.runner import explicit_ends

    destination = Path(destination)
    path = destination / "acquisition.json"
    state = loads(path.read_bytes())
    store = EvidenceStore(destination / "evidence")
    state.setdefault("original_failures", {})
    owned = client is None
    client = client or SECClient(
        cache_dir=destination / "cache", limiter=RateLimiter(2.0), max_retries=1
    )

    class Recording:
        def filing_document(self, cik, accession, filename, *, refresh=False):
            key = "/".join((cik, "filing_document", accession, filename))
            if key in state["artifacts"]:
                return store.raw(store._artifact(state["artifacts"][key]))
            raw = client.filing_document(cik, accession, filename, refresh=refresh)
            family = (
                "filing_directory"
                if filename == "index.json" or filename.endswith("-index.html")
                else "xbrl_instance"
            )
            artifact = store.capture(
                raw, source_family=family, cik=cik, accession=accession, authenticity="authentic"
            )
            state["artifacts"][key] = asdict(artifact)
            atomic_write(path, dumps(state).encode())
            return raw

    try:
        for issuer in selection(manifest, tier="A"):
            cik = issuer["cik"]
            key = f"{cik}/{fiscal_year}"
            try:
                ends = explicit_ends(store, state["snapshot_id"], cik, (fiscal_year,), ("FY",))
                if not ends:
                    raise ValidationError("No explicit annual balance date")
                with SECClient(cache_dir=destination / "cache", offline=True) as offline:
                    timeline = filings.timeline(cik, client=offline)
                candidates = [
                    f
                    for event in timeline
                    for f in event.source_records
                    if f.form == "10-K" and f.report_date == ends[0].end
                ]
                if not candidates:
                    raise ValidationError("No linked annual filing")
                filing = min(candidates, key=lambda f: (f.filing_date, f.accession_number))
                sources = xbrl.discover(filing, client=Recording())
                if not sources.instances:
                    raise ValidationError("No declared original instance")
                for document in sources.instances:
                    xbrl.retrieve(document, client=Recording())
                state["original_failures"].pop(key, None)
            except FinPanelError as exc:
                state["original_failures"][key] = {
                    "category": "original_source_acquisition_failure",
                    "error_type": type(exc).__name__,
                    "status": getattr(exc, "status", None),
                }
            atomic_write(path, dumps(state).encode())
        snapshot = store.create(
            [store._artifact(a) for a in state["artifacts"].values()],
            scope=store.load(state["snapshot_id"]).manifest["scope"],
            required_urls=store.load(state["snapshot_id"]).manifest["required_urls"],
            incompleteness=(
                "Original XBRL acquired only for selected Tier A annual filings; "
                "not all source accessions",
            ),
        )
        state["snapshot_id"] = snapshot.snapshot_id
        atomic_write(path, dumps(state).encode())
        return state
    finally:
        if owned:
            client.close()
