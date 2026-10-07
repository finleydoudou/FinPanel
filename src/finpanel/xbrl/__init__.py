"""Inspectable original filing evidence; default WP1/WP2 selection stays unchanged."""

from finpanel.models import Filing
from finpanel.sec.client import SECClient
from finpanel.xbrl.discovery import FilingSources, SourceDocument, discover, retrieve
from finpanel.xbrl.integration import revision_evidence, verify_derivation, verify_metric
from finpanel.xbrl.models import InstanceEvidence
from finpanel.xbrl.parser import parse_instance
from finpanel.xbrl.verification import SourceVerification, context_for_fact, verify_fact


def inspect_filing(
    filing: Filing, *, client: SECClient
) -> tuple[FilingSources, tuple[InstanceEvidence, ...]]:
    """Discover a known filing and parse all declared supported instances.

    Missing cache/network failures remain explicit exceptions. Unsupported XML
    raises ValidationError, never becomes successful original verification.
    """
    sources = discover(filing, client=client)
    instances = []
    for document in sources.instances:
        document, raw = retrieve(document, client=client)
        instances.append(parse_instance(raw, document))
    return sources, tuple(instances)


__all__ = [
    "verify_metric",
    "verify_derivation",
    "revision_evidence",
    "FilingSources",
    "SourceDocument",
    "InstanceEvidence",
    "SourceVerification",
    "discover",
    "inspect_filing",
    "parse_instance",
    "verify_fact",
    "context_for_fact",
]
