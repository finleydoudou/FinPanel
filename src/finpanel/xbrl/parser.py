"""Narrow non-validating XBRL 2.1 evidence reader; no DTD or schema/network loading."""

import io
import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from finpanel.errors import ValidationError
from finpanel.models import RawResponse
from finpanel.serialization import dumps
from finpanel.xbrl.discovery import SourceDocument
from finpanel.xbrl.models import (
    Dimension,
    InstanceEvidence,
    NumericMetadata,
    OriginalContext,
    OriginalFact,
    OriginalUnit,
)

XBRLI = "http://www.xbrl.org/2003/instance"
D = "http://xbrl.org/2006/xbrldi"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ISO = "http://www.xbrl.org/2003/iso4217"


def tag(namespace, name):
    return "{" + namespace + "}" + name


def fingerprint(value):
    return sha256(dumps(value).encode()).hexdigest()


def numeric_metadata(decimals: str | None, precision: str | None) -> NumericMetadata:
    if decimals is not None and precision is not None:
        return NumericMetadata(decimals, precision, "unsupported_both_attributes", None, None)
    if decimals == "INF":
        return NumericMetadata(decimals, precision, "exact", Decimal(0), Decimal(0))
    if decimals is not None and re.fullmatch(r"[+-]?\d+", decimals):
        n = int(decimals)
        if abs(n) <= 10000:
            quantum = Decimal((0, (1,), -n))
            half = Decimal((0, (5,), -n - 1))
            return NumericMetadata(decimals, precision, "rounded", quantum, half)
    if decimals is None and precision is None:
        state = "unspecified"
    elif decimals is None:
        state = (
            "precision_preserved_not_interpreted"
            if precision == "INF" or re.fullmatch(r"\+?[1-9]\d*", precision or "")
            else "unsupported_precision"
        )
    else:
        state = "unsupported_decimals"
    return NumericMetadata(decimals, precision, state, None, None)


def _date(text):
    try:
        return date.fromisoformat(text) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text or "") else None
    except ValueError:
        return None


def parse_instance(raw: RawResponse, document: SourceDocument) -> InstanceEvidence:
    if raw.sha256 != document.content_sha256 or raw.url != document.url:
        raise ValidationError("Instance bytes do not match source identity")
    if len(raw.body) > 50_000_000:
        raise ValidationError("Instance exceeds supported 50 MB size")
    # Decode before security checks so UTF-16 cannot conceal entity declarations.
    text = raw.text()
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        raise ValidationError("DTD and entity declarations are unsupported")
    scopes, stack, pending = {}, [], {}
    try:
        for event, obj in ET.iterparse(io.StringIO(text), events=("start-ns", "start", "end")):
            if event == "start-ns":
                pending[obj[0]] = obj[1]
            elif event == "start":
                scope = dict(stack[-1]) if stack else {}
                scope.update(pending)
                pending.clear()
                scopes[id(obj)] = scope
                stack.append(scope)
            else:
                stack.pop()
                root = obj
    except ET.ParseError as exc:
        raise ValidationError("Unsupported or malformed XBRL XML") from exc
    if root.tag != tag(XBRLI, "xbrl"):
        raise ValidationError("Document is not an XBRL 2.1 instance; Inline HTML is unsupported")

    def qname(value, node):
        value = (value or "").strip()
        prefix, local = value.split(":", 1) if ":" in value else ("", value)
        uri = scopes[id(node)].get(prefix)
        if uri is None or not local:
            raise ValueError("Unresolved QName")
        return tag(uri, local)

    def xml(node):
        return ET.tostring(node, encoding="unicode") if node is not None else None

    contexts, units, facts, diagnostics = [], [], [], []
    ids = set()
    for position, node in enumerate(root):
        prov = raw.provenance(f"/xbrli:xbrl/*[{position + 1}]")
        ident = node.get("id")
        if ident:
            if ident in ids:
                raise ValidationError("Duplicate XML ID in instance")
            ids.add(ident)
        if node.tag == tag(XBRLI, "context"):
            issues = []
            identifier = node.find(f"{tag(XBRLI, 'entity')}/{tag(XBRLI, 'identifier')}")
            entity = identifier.text.strip() if identifier is not None and identifier.text else None
            scheme = identifier.get("scheme") if identifier is not None else None
            entity_node = node.find(tag(XBRLI, "entity"))
            if (
                len(node.findall(tag(XBRLI, "entity"))) != 1
                or len(node.findall(tag(XBRLI, "period"))) != 1
                or len(node.findall(tag(XBRLI, "scenario"))) > 1
                or entity_node is None
                or entity_node.attrib
                or len(entity_node.findall(tag(XBRLI, "identifier"))) != 1
                or len(entity_node.findall(tag(XBRLI, "segment"))) > 1
                or any(
                    c.tag not in {tag(XBRLI, "identifier"), tag(XBRLI, "segment")}
                    for c in entity_node
                )
                or identifier is None
                or len(identifier)
                or set(identifier.attrib) != {"scheme"}
            ):
                issues.append("unsupported_entity_structure")
            period = node.find(tag(XBRLI, "period"))
            if period is not None and (period.attrib or any(c.attrib or len(c) for c in period)):
                issues.append("unsupported_period_structure")
            start = end = None
            kind = "unknown"
            if period is not None and len(period) == 1 and period[0].tag == tag(XBRLI, "instant"):
                kind, end = "instant", _date(period[0].text)
            elif period is not None and len(period) == 2:
                start = _date(period.findtext(tag(XBRLI, "startDate")))
                end = _date(period.findtext(tag(XBRLI, "endDate")))
                kind = "duration"
            if (
                not entity
                or not scheme
                or not end
                or (kind == "duration" and (not start or start > end))
            ):
                issues.append("unsupported_entity_or_period")
            segment = node.find(f"{tag(XBRLI, 'entity')}/{tag(XBRLI, 'segment')}")
            scenario = node.find(tag(XBRLI, "scenario"))
            dims, other = [], []
            for location, container in [("segment", segment), ("scenario", scenario)]:
                if container is None:
                    continue
                if container.attrib or (container.text or "").strip():
                    other.append(location + ":" + xml(container))
                    issues.append("unsupported_scope_container")
                for child in container:
                    try:
                        if child.tag == tag(D, "explicitMember") and not list(child):
                            dims.append(
                                Dimension(
                                    qname(child.get("dimension"), child),
                                    "explicit",
                                    qname(child.text, child),
                                    None,
                                    location,
                                )
                            )
                            if set(child.attrib) != {"dimension"}:
                                issues.append("unsupported_dimension_attributes")
                        elif child.tag == tag(D, "typedMember") and len(child) == 1:
                            dims.append(
                                Dimension(
                                    qname(child.get("dimension"), child),
                                    "typed",
                                    None,
                                    xml(child[0]),
                                    location,
                                )
                            )
                            # Preserve typed XML; schema-defined equality is not implemented.
                            issues.append("typed_dimension_semantics_unsupported")
                        else:
                            other.append(location + ":" + xml(child))
                            issues.append("non_dimensional_scope_present")
                    except ValueError:
                        other.append(location + ":" + xml(child))
                        issues.append("unresolved_dimension_qname")
            dims = tuple(
                sorted(dims, key=lambda d: (d.location, d.axis, d.member or "", d.typed_xml or ""))
            )
            if len({d.axis for d in dims}) != len(dims):
                issues.append("duplicate_dimension_axis")
            if set(node.attrib) - {"id"} or any(
                c.tag not in {tag(XBRLI, "entity"), tag(XBRLI, "period"), tag(XBRLI, "scenario")}
                for c in node
            ):
                issues.append("unsupported_context_structure")
            state = "unknown" if issues else ("explicit" if dims else "undimensioned")
            if any(d.kind == "typed" for d in dims):
                state = "typed"
            scope = (entity, scheme, dims, tuple(other), tuple(issues))
            contexts.append(
                OriginalContext(
                    ident or "",
                    entity,
                    scheme,
                    kind,
                    start,
                    end,
                    dims,
                    state,
                    xml(segment),
                    xml(scenario),
                    tuple(other),
                    fingerprint((scope, kind, start, end)),
                    fingerprint(scope),
                    prov,
                    xml(node),
                    tuple(issues),
                )
            )
        elif node.tag == tag(XBRLI, "unit"):
            issues = []
            if set(node.attrib) - {"id"} or any(
                c.attrib or (c.tag == tag(XBRLI, "measure") and len(c))
                for c in node.iter()
                if c is not node
            ):
                issues.append("unsupported_unit_attributes_or_structure")
            numerator, denominator = [], []
            try:
                if all(c.tag == tag(XBRLI, "measure") for c in node) and len(node):
                    numerator = [qname(c.text, c) for c in node]
                else:
                    divide = node.find(tag(XBRLI, "divide"))
                    if divide is None or len(node) != 1 or len(divide) != 2:
                        raise ValueError("Unsupported unit")
                    for name, values in [
                        ("unitNumerator", numerator),
                        ("unitDenominator", denominator),
                    ]:
                        parent = divide.find(tag(XBRLI, name))
                        if parent is None or not len(parent):
                            raise ValueError("Unsupported unit")
                        for child in parent:
                            if child.tag != tag(XBRLI, "measure"):
                                raise ValueError("Unsupported unit")
                            values.append(qname(child.text, child))
            except ValueError:
                issues.append("unsupported_unit")
            numerator, denominator = tuple(sorted(numerator)), tuple(sorted(denominator))
            units.append(
                OriginalUnit(
                    ident or "",
                    numerator,
                    denominator,
                    fingerprint((numerator, denominator)),
                    xml(node),
                    prov,
                    tuple(issues),
                )
            )
        elif node.get("contextRef") is not None:
            namespace, concept = (
                node.tag[1:].split("}", 1) if node.tag.startswith("{") else ("", node.tag)
            )
            lexical = node.text or ""
            nil = node.get(tag(XSI, "nil")) in {"true", "1"}
            issues = []
            if node.get(tag(XSI, "nil")) not in {None, "true", "false", "1", "0"}:
                issues.append("unsupported_nil_attribute")
            value = None if nil else lexical
            if list(node):
                issues.append("nested_fact_content_unsupported")
            if node.get("unitRef") and not nil:
                try:
                    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", lexical.strip()):
                        raise InvalidOperation
                    value = Decimal(lexical.strip())
                except InvalidOperation:
                    value = None
                    issues.append("unsupported_numeric_lexical")
            known = {"id", "contextRef", "unitRef", "decimals", "precision", tag(XSI, "nil")}
            if set(node.attrib) - known:
                issues.append("additional_fact_attributes_preserved")
            facts.append(
                OriginalFact(
                    namespace,
                    concept,
                    node.get("contextRef"),
                    node.get("unitRef"),
                    lexical,
                    value,
                    nil,
                    numeric_metadata(node.get("decimals"), node.get("precision")),
                    tuple(sorted(node.attrib.items())),
                    prov,
                    tuple(issues),
                )
            )
        elif node.tag not in {
            tag("http://www.xbrl.org/2003/linkbase", "schemaRef"),
            tag("http://www.xbrl.org/2003/linkbase", "footnoteLink"),
        }:
            diagnostics.append("unsupported_top_level_element:" + node.tag)
    if any(not c.context_id for c in contexts) or any(not u.unit_id for u in units):
        raise ValidationError("Missing context or unit ID")
    return InstanceEvidence(
        document, tuple(contexts), tuple(units), tuple(facts), tuple(diagnostics)
    )
