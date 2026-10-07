"""Official SEC directory inventory plus filing-index document declarations."""

from dataclasses import dataclass, replace
from datetime import date
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from finpanel.errors import ValidationError
from finpanel.models import Filing, Provenance, RawResponse
from finpanel.sec.client import SECClient
from finpanel.serialization import loads


@dataclass(frozen=True)
class SourceDocument:
    cik: str
    accession: str
    form: str | None
    filing_date: date | None
    filename: str
    url: str
    document_type: str
    sequence: str | None
    description: str | None
    declared_type: str | None
    discovery: tuple[Provenance, ...]
    content_sha256: str | None = None
    retrieved_at: str | None = None
    raw_unmodified: bool = True
    from_cache: bool = False
    discovery_retrieved_at: tuple[str, ...] = ()


@dataclass(frozen=True)
class FilingSources:
    filing: Filing
    documents: tuple[SourceDocument, ...]
    metadata: tuple[RawResponse, ...]
    diagnostics: tuple[str, ...]

    @property
    def instances(self) -> tuple[SourceDocument, ...]:
        return tuple(d for d in self.documents if d.document_type == "instance")


class _Index(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if len(self.row) >= 4:
                self.rows.append(self.row)
            self.row = None


_TYPES = {
    "EX-101.INS": "instance",
    "EX-101.SCH": "schema",
    "EX-101.CAL": "calculation",
    "EX-101.DEF": "definition",
    "EX-101.LAB": "label",
    "EX-101.PRE": "presentation",
}


def discover(filing: Filing, *, client: SECClient, refresh: bool = False) -> FilingSources:
    """Use structured inventory; classify from SEC index declarations, never suffix guesses."""
    raw = client.filing_document(filing.cik, filing.accession_number, "index.json", refresh=refresh)
    directory = loads(raw.body).get("directory", {})
    items = directory.get("item")
    expected = f"/Archives/edgar/data/{int(filing.cik)}/{filing.accession_number.replace('-', '')}"
    if directory.get("name", "").rstrip("/") != expected or not isinstance(items, list):
        raise ValidationError("SEC directory metadata does not match requested filing")
    inventory = {}
    for i, item in enumerate(items):
        name = item.get("name")
        if not isinstance(name, str) or name in inventory:
            raise ValidationError("Invalid or duplicate directory entry")
        inventory[name] = i
    # The index endpoint is a documented accession-based metadata endpoint, not a
    # guessed instance filename. Directory inventories do not always list it.
    index_name = filing.accession_number + "-index.html"
    index = client.filing_document(filing.cik, filing.accession_number, index_name, refresh=refresh)
    parser = _Index()
    parser.feed(index.text())
    declarations = {}
    for i, row in enumerate(parser.rows):
        sequence, description, name, declared = row[:4]
        name = name.removesuffix(" iXBRL").strip()
        if name not in inventory:
            continue
        if name in declarations:
            raise ValidationError("Conflicting duplicate filing-index document declarations")
        declarations[name] = (sequence, description, declared, i)
    docs = []
    for name, i in sorted(inventory.items()):
        # Reject path injection even for unrequested inventory entries.
        import re

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or ".." in name:
            raise ValidationError("Unsafe directory document name")
        seq, desc, declared, row = declarations.get(name, (None, None, None, None))
        kind = _TYPES.get(declared, "other")
        if declared == "XML" and desc and desc.upper() == "EXTRACTED XBRL INSTANCE DOCUMENT":
            kind = "instance"
        if name == filing.primary_document:
            kind = "primary"
        if name == "index.json" or name == index_name:
            kind = "directory"
        evidence = (raw.provenance(f"/directory/item/{i}"),)
        if row is not None:
            evidence += (index.provenance(f"table-row[{row}]"),)
        docs.append(
            SourceDocument(
                filing.cik,
                filing.accession_number,
                filing.form,
                filing.filing_date,
                name,
                raw.url.rsplit("/", 1)[0] + "/" + name,
                kind,
                seq,
                desc,
                declared,
                evidence,
                discovery_retrieved_at=(raw.retrieved_at, index.retrieved_at),
            )
        )
    issues = []
    if not declarations:
        issues.append("index_document_declarations_unavailable")
    if not any(d.document_type == "instance" for d in docs):
        issues.append("supported_instance_unavailable")
    return FilingSources(filing, tuple(docs), (raw, index), tuple(issues))


def retrieve(document: SourceDocument, *, client: SECClient) -> tuple[SourceDocument, RawResponse]:
    raw = client.filing_document(document.cik, document.accession, document.filename)
    if (
        raw.url != document.url
        or unquote(urlsplit(raw.url).path).split("/")[-1] != document.filename
    ):
        raise ValidationError("Source document URL mismatch")
    return replace(
        document,
        content_sha256=raw.sha256,
        retrieved_at=raw.retrieved_at,
        from_cache=raw.from_cache,
    ), raw
