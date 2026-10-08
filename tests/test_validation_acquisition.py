"""Synthetic transport interruptions; no live SEC access or authentic fixture labels."""

import pytest
from test_snapshots_pipeline import sources

from finpanel.errors import SECRequestError, ValidationError
from finpanel.snapshots import SnapshotError
from finpanel.validation.acquisition import acquire
from finpanel.validation.universe import universe


def manifest():
    data = universe()
    data["issuers"] = [dict(data["issuers"][0], cik="0000000001", tier_a=True)]
    return data


class Client:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def submissions(self, cik):
        self.calls.append("submissions")
        return sources()[1]

    def companyfacts(self, cik):
        self.calls.append("companyfacts")
        if self.fail:
            raise SECRequestError("synthetic interruption", url="https://data.sec.gov", attempts=1)
        return sources()[0]


def test_resume_reuses_success_and_retries_only_failure(tmp_path):
    a = Client(True)
    first = acquire(tmp_path, manifest=manifest(), client=a)
    assert len(first["failures"]) == 1 and len(first["artifacts"]) == 1
    b = Client()
    second = acquire(tmp_path, manifest=manifest(), client=b)
    assert b.calls == ["companyfacts"] and second["failures"] == {}
    c = Client()
    third = acquire(tmp_path, manifest=manifest(), client=c)
    assert c.calls == [] and third["snapshot_id"] == second["snapshot_id"]


def test_resume_corruption_is_not_downloaded_or_repaired(tmp_path):
    result = acquire(tmp_path, manifest=manifest(), client=Client())
    artifact = next(iter(result["artifacts"].values()))
    (tmp_path / "evidence" / artifact["locator"]).write_bytes(b"corrupt")
    client = Client()
    with pytest.raises(SnapshotError):
        acquire(tmp_path, manifest=manifest(), client=client)
    assert client.calls == []


def test_resume_rejects_scope_change(tmp_path):
    acquire(tmp_path, manifest=manifest(), client=Client())
    with pytest.raises(ValidationError, match="configuration"):
        acquire(tmp_path, manifest=manifest(), client=Client(), history=False)


def test_http_failure_status_is_preserved(tmp_path):
    class Denied(Client):
        def companyfacts(self, cik):
            raise SECRequestError(
                "synthetic denial", url="https://data.sec.gov", attempts=1, status=403
            )

    result = acquire(tmp_path, manifest=manifest(), client=Denied())
    failure = next(iter(result["failures"].values()))
    assert failure == {
        "category": "acquisition_failure",
        "error_type": "SECRequestError",
        "status_code": 403,
    }
