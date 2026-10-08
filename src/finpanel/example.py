"""Build and replay a small authentic frozen panel without credentials or network.

Run ``python -m finpanel.example output/quickstart`` in a fresh directory. This
onboarding workflow is experimental; the underlying panel API is documented.
"""

import argparse
from importlib.resources import as_file, files
from pathlib import Path

from finpanel import panel
from finpanel.errors import ValidationError
from finpanel.serialization import dumps
from finpanel.snapshots import EvidenceStore
from finpanel.validation.fixtures import import_fixtures


def build_example(destination: str | Path) -> dict:
    """Export six FY2022 HRB cells and verify replay using bundled SEC byte captures."""
    out = Path(destination)
    if out.exists():
        raise ValidationError("Example output must be a new directory")
    out.mkdir(parents=True)
    store = EvidenceStore(out / "evidence")
    with as_file(files("finpanel").joinpath("example_data")) as folder:
        snapshot = import_fixtures(folder, store)
    request = panel.PanelRequest(
        entities=("12659",),
        metrics=(
            "revenue",
            "net_income",
            "operating_cash_flow",
            "assets",
            "liabilities",
            "cash_and_cash_equivalents",
        ),
        fiscal_years=(2022,),
        periods=("FY",),
        as_of=("2022-08-17T12:00:00Z",),
        snapshot_id=snapshot.snapshot_id,
        period_ends=(panel.PeriodEnd("12659", 2022, "FY", "2022-06-30"),),
    )
    result = panel.build(request, store=store)
    for suffix in ("parquet", "csv", "duckdb"):
        panel.export(result, out / ("panel." + suffix))
    (out / "receipt.json").write_text(dumps(result.receipt), encoding="utf-8")
    replayed = panel.reproduce(result.receipt, store=store)
    if replayed.receipt.receipt_id != result.receipt.receipt_id:
        raise ValidationError("Example replay mismatch")
    summary = dict(
        snapshot_id=snapshot.snapshot_id,
        receipt_id=result.receipt.receipt_id,
        cells=len(result.rows),
        resolved=sum(r.value is not None for r in result.rows),
        replay_verified=True,
        provenance_row=next(r.row_id for r in result.rows if r.metric == "revenue"),
    )
    (out / "summary.json").write_text(dumps(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(dumps(build_example(args.destination)))


if __name__ == "__main__":
    main()
