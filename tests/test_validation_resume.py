"""Offline resume equivalence, corruption rejection, and issuer failure isolation."""

from dataclasses import replace

import pytest
from test_panel_engine import pinned
from test_validation_acquisition import manifest

from finpanel.errors import ValidationError
from finpanel.serialization import loads
from finpanel.validation import runner
from finpanel.validation.checkpoints import Checkpoint


def config():
    return runner.BenchmarkConfig(
        fiscal_years=(2021,),
        periods=("FY",),
        as_of=("2025-01-01T00:00:00Z",),
        revision_policies=("latest_available",),
        source_verification=False,
    )


def two_issuers():
    data = manifest()
    data["issuers"].append(dict(data["issuers"][0], cik="0000000002"))
    return data


def test_interrupted_resume_matches_continuous_and_skips_completed(tmp_path, monkeypatch):
    store, req = pinned(tmp_path / "store")
    kwargs = dict(manifest=two_issuers(), config=config())
    full, receipt, _ = runner.run(store, req.snapshot_id, tmp_path / "continuous", **kwargs)
    finish = Checkpoint.complete
    completed = []

    def interrupt(self, cik, state):
        finish(self, cik, state)
        completed.append(cik)
        raise KeyboardInterrupt("simulated process interruption after durable checkpoint")

    monkeypatch.setattr(Checkpoint, "complete", interrupt)
    out = tmp_path / "resumed"
    with pytest.raises(KeyboardInterrupt):
        runner.run(store, req.snapshot_id, out, **kwargs)
    assert completed == ["0000000001"]
    monkeypatch.setattr(Checkpoint, "complete", finish)
    prepare = runner.explicit_ends
    visited = []

    def observe(*args):
        visited.append(args[2])
        return prepare(*args)

    monkeypatch.setattr(runner, "explicit_ends", observe)
    resumed, resumed_receipt, _ = runner.run(store, req.snapshot_id, out, resume=True, **kwargs)
    assert visited == ["0000000002"]
    assert resumed == full
    assert resumed_receipt == receipt


@pytest.mark.parametrize("change", ["config", "subset", "snapshot", "software"])
def test_incompatible_job_rejected(tmp_path, monkeypatch, change):
    store, req = pinned(tmp_path / "store")
    out = tmp_path / "report"
    cfg = config()
    runner.run(store, req.snapshot_id, out, manifest=two_issuers(), config=cfg)
    args = dict(manifest=two_issuers(), config=cfg, resume=True)
    if change == "config":
        args["config"] = replace(cfg, replay=False)
    elif change == "subset":
        args["subset"] = ["0000000001"]
    elif change == "snapshot":
        # Another valid immutable snapshot over the same raw bytes is still different.
        snap = store.load(req.snapshot_id)
        new = store.create([store._artifact(a) for a in snap.manifest["artifacts"]], scope="new")
        req = replace(req, snapshot_id=new.snapshot_id)
    else:
        monkeypatch.setattr(runner, "software_identity", lambda: {"version": "changed"})
    with pytest.raises(ValidationError, match="Incompatible"):
        runner.run(store, req.snapshot_id, out, **args)


@pytest.mark.parametrize("target", ["checkpoint", "panel", "receipt"])
def test_corrupt_checkpoint_or_output_is_rejected(tmp_path, target):
    store, req = pinned(tmp_path / "store")
    out = tmp_path / "report"
    runner.run(store, req.snapshot_id, out, manifest=manifest(), config=config())
    path = (
        out / "checkpoint.json"
        if target == "checkpoint"
        else out
        / "0000000001/latest_available"
        / ("panel.parquet" if target == "panel" else "receipt.json")
    )
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ValidationError):
        runner.run(store, req.snapshot_id, out, manifest=manifest(), config=config(), resume=True)


def test_unexpected_parser_failure_is_terminal_and_prior_work_preserved(tmp_path, monkeypatch):
    store, req = pinned(tmp_path / "store")
    original = runner.explicit_ends

    def fail_second(*args):
        if args[2] == "0000000002":
            raise RuntimeError("synthetic parser failure")
        return original(*args)

    monkeypatch.setattr(runner, "explicit_ends", fail_second)
    out = tmp_path / "report"
    report, _, _ = runner.run(store, req.snapshot_id, out, manifest=two_issuers(), config=config())
    assert report["observed_cells"] == 6
    assert report["unexpected_findings"] == [
        dict(
            cik="0000000002",
            category="batch_execution_failure",
            error_type="RuntimeError",
            disposition="terminal_recorded",
        )
    ]
    assert len(loads((out / "checkpoint.json").read_bytes())["completed"]) == 2
    assert (out / "0000000001/latest_available/panel.parquet").is_file()


def test_incomplete_batch_is_preserved_and_recomputed(tmp_path, monkeypatch):
    store, req = pinned(tmp_path / "store")
    original = Checkpoint.complete
    monkeypatch.setattr(
        Checkpoint, "complete", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    out = tmp_path / "report"
    with pytest.raises(KeyboardInterrupt):
        runner.run(store, req.snapshot_id, out, manifest=manifest(), config=config())
    monkeypatch.setattr(Checkpoint, "complete", original)
    report, _, _ = runner.run(
        store, req.snapshot_id, out, manifest=manifest(), config=config(), resume=True
    )
    assert report["unexpected_mismatches"] == 0
    assert list((out / ".interrupted").glob("*/latest_available/panel.parquet"))


def test_worker_bound_is_explicit(tmp_path):
    store, req = pinned(tmp_path / "store")
    with pytest.raises(ValidationError, match="one deterministic"):
        runner.run(store, req.snapshot_id, tmp_path / "report", workers=2)


def test_job_lock_prevents_concurrent_writers_and_releases(tmp_path):
    from finpanel.validation.checkpoints import job_lock

    with job_lock(tmp_path / "lock"):
        with pytest.raises(ValidationError, match="already running"), job_lock(tmp_path / "lock"):
            pass
    with job_lock(tmp_path / "lock"):
        pass


def test_checkpoint_location_and_semantic_order_normalization(tmp_path):
    store, req = pinned(tmp_path / "store")
    cfg = replace(config(), fiscal_years=(2021, 2021), periods=("Q1", "FY"))
    out = tmp_path / "report"
    checkpoint = tmp_path / "job.json"
    first, _, _ = runner.run(
        store, req.snapshot_id, out, manifest=manifest(), config=cfg, checkpoint=checkpoint
    )
    second, _, _ = runner.run(
        store,
        req.snapshot_id,
        out,
        manifest=manifest(),
        config=replace(cfg, fiscal_years=(2021,), periods=("FY", "Q1")),
        checkpoint=checkpoint,
        resume=True,
    )
    assert first == second
