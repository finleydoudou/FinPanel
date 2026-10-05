"""Required offline acceptance checks for the authentic frozen SEC snapshots."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path

from finpanel.models import RawResponse
from finpanel.sec import parse_companyfacts, parse_submissions
from finpanel.serialization import dumps, loads

ROOT = Path(__file__).parent / "fixtures" / "sec"


def test_authentic_sec_snapshots():
    manifest = loads((ROOT / "manifest.json").read_bytes())
    assert manifest["kind"] == "official_sec_snapshots"
    assert set(manifest["files"]) == {
        f"{ticker}_{endpoint}.json"
        for ticker in ("aapl", "msft", "wmt", "nvda")
        for endpoint in ("submissions", "companyfacts")
    }
    for filename, meta in manifest["files"].items():
        body = (ROOT / filename).read_bytes()
        assert sha256(body).hexdigest() == meta["sha256"]
        endpoint = "submissions" if "submissions" in filename else "api/xbrl/companyfacts"
        assert meta["source_url"] == f"https://data.sec.gov/{endpoint}/CIK{meta['cik']}.json"
        assert meta["raw_unmodified"] is True
        assert meta["purpose"]
        assert datetime.fromisoformat(meta["retrieved_at"]).tzinfo is not None
        source = RawResponse(meta["source_url"], body, meta["retrieved_at"])
        parse = parse_submissions if "submissions" in filename else parse_companyfacts
        result = parse(source)
        assert result.records
        assert not result.issues
        assert {r.cik for r in result.records} == {meta["cik"]}
        assert len(result.records) == meta["records"]
        assert len(result.issues) == meta["issues"]
        assert dumps(result) == dumps(parse(source))
        data = source.json()
        if "submissions" in filename:
            columns = data["filings"]["recent"]
            assert len(result.records) == len(columns["accessionNumber"])
            assert [r.form for r in result.records] == columns["form"]
            for i, record in enumerate(result.records):
                assert record.raw == {key: values[i] for key, values in columns.items()}
        else:
            count = sum(
                len(observations)
                for concepts in data["facts"].values()
                for details in concepts.values()
                for observations in details["units"].values()
            )
            assert len(result.records) == count
            for record in result.records:
                index = int(record.provenance.pointer.rsplit("/", 1)[1])
                assert (
                    record.raw
                    == data["facts"][record.taxonomy][record.concept]["units"][record.unit][index]
                )
