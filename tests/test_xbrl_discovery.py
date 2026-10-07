"""Synthetic metadata and HTTP transport tests; no live requests."""

from dataclasses import replace
from datetime import date

import httpx
import pytest

from finpanel.errors import CacheMissError, ValidationError
from finpanel.models import Filing, Provenance, RawResponse
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps
from finpanel.xbrl.discovery import discover, retrieve

ACC = "0000320193-24-000069"
BASE = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000069/"
FILING = Filing(
    "0000320193",
    "Apple",
    ACC,
    date(2024, 5, 3),
    date(2024, 3, 30),
    None,
    "10-Q",
    "primary.htm",
    None,
    Provenance("synthetic", "hash", "/"),
    {},
)


def seed(cache, *, include=True, description="EXTRACTED XBRL INSTANCE DOCUMENT"):
    names = ["primary.htm", "not-a-filename-guess.xml", "extension.xsd", "other.xml"]
    directory = {
        "directory": {
            "name": "/Archives/edgar/data/320193/000032019324000069",
            "item": [{"name": n} for n in names],
        }
    }
    body = "<table><tr><td>1</td><td>PRIMARY</td><td>primary.htm</td><td>10-Q</td></tr>"
    if include:
        body += (
            f"<tr><td>8</td><td>{description}</td>"
            f"<td>not-a-filename-guess.xml</td><td>XML</td></tr>"
        )
    body += "<tr><td>2</td><td>SCHEMA</td><td>extension.xsd</td><td>EX-101.SCH</td></tr></table>"
    for name, data in [
        ("index.json", dumps(directory).encode()),
        (ACC + "-index.html", body.encode()),
        ("not-a-filename-guess.xml", b"<xbrl/>"),
    ]:
        cache.put(RawResponse(BASE + name, data, "2026-10-07T00:00:00+00:00", raw_format="text"))


def test_metadata_discovery_and_raw_cache(tmp_path):
    with SECClient(offline=True, cache_dir=tmp_path) as client:
        seed(client.cache)
        sources = discover(FILING, client=client)
        assert [d.filename for d in sources.instances] == ["not-a-filename-guess.xml"]
        assert len(sources.instances[0].discovery) == 2
        doc, raw = retrieve(sources.instances[0], client=client)
        assert doc.content_sha256 == raw.sha256 and doc.from_cache
        assert doc.retrieved_at and doc.raw_unmodified
        assert {d.document_type for d in sources.documents} == {
            "primary",
            "schema",
            "instance",
            "other",
        }


def test_no_filename_classification(tmp_path):
    with SECClient(offline=True, cache_dir=tmp_path) as client:
        seed(client.cache, include=False)
        assert not discover(FILING, client=client).instances
        with pytest.raises(CacheMissError):
            client.filing_document(FILING.cik, ACC, "missing.xml")


@pytest.mark.parametrize(
    "name", ["../outside.xml", "x/y.xml", "https://evil.invalid/x", "a?x=1", "%2e%2e"]
)
def test_archive_path_safety(name, tmp_path):
    with SECClient(offline=True, cache_dir=tmp_path) as client:
        with pytest.raises(ValidationError):
            client.filing_document(FILING.cik, ACC, name)


def test_directory_identity(tmp_path):
    with SECClient(offline=True, cache_dir=tmp_path) as client:
        seed(client.cache)
        raw = client.cache.get(BASE + "index.json")
        client.cache.put(replace(raw, body=raw.body.replace(b"320193", b"320194")))
        with pytest.raises(ValidationError):
            discover(FILING, client=client)


def test_transport_preserves_bytes(tmp_path, limiter):
    body = b'<?xml version="1.0"?>\n<xbrl>unchanged</xbrl>\n'
    with SECClient(
        "Synthetic tests",
        cache_dir=tmp_path,
        limiter=limiter,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
    ) as c:
        raw = c.filing_document(FILING.cik, ACC, "instance.xml")
        assert raw.body == body
        assert c.filing_document(FILING.cik, ACC, "instance.xml").from_cache
