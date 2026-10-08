"""Versioned purposive issuer universe, never a historical security master."""

from importlib.resources import files

from finpanel.errors import ValidationError
from finpanel.sec.common import normalize_cik
from finpanel.serialization import loads
from finpanel.snapshots.store import digest


def validate_universe(data):
    if data.get("format") != "finpanel-validation-universe-v1":
        raise ValidationError("Unknown validation universe format")
    seen = set()
    for issuer in data["issuers"]:
        cik = normalize_cik(issuer["cik"])
        if cik != issuer["cik"] or cik in seen:
            raise ValidationError("Duplicate or noncanonical universe CIK")
        seen.add(cik)
        if issuer["status"] not in {"included", "excluded"}:
            raise ValidationError("Unknown inclusion status")
        if issuer["status"] == "excluded" and (issuer["tier_a"] or issuer["tier_b"]):
            raise ValidationError("Excluded issuer cannot enter either core tier")
        if issuer["tier_a"] and not issuer["tier_b"]:
            raise ValidationError("Tier A must be a subset of Tier B")
        if not issuer["selection_rationale"] or not issuer["category"]:
            raise ValidationError("Issuer selection requires a rationale and category")
    return data


def universe():
    return validate_universe(loads(files(__package__).joinpath("universe.json").read_bytes()))


def selection(data=None, *, tier="B", limit=None):
    if tier not in {"A", "B"}:
        raise ValidationError("Tier must be A or B")
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 100):
        raise ValidationError("Explicit issuer limit must be between 1 and 100")
    data = validate_universe(data if data is not None else universe())
    selected = sorted(
        (i for i in data["issuers"] if i["status"] == "included" and i["tier_" + tier.lower()]),
        key=lambda i: i["cik"],
    )
    return tuple(selected if limit is None else selected[:limit])


def universe_hash(data=None):
    return digest(validate_universe(data if data is not None else universe()))
