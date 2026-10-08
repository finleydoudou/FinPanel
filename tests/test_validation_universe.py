from copy import deepcopy

import pytest

from finpanel.errors import ValidationError
from finpanel.validation.universe import selection, universe, universe_hash, validate_universe


def test_fixed_universe_tiers_and_exclusions():
    data = universe()
    assert len(selection(data)) == 50
    assert len(selection(data, tier="A")) == 13
    assert len({r["category"] for r in selection(data)}) == 12
    assert len([r for r in data["issuers"] if r["status"] == "excluded"]) == 5
    assert all(
        r["cik"] not in {"0000320193", "0000789019", "0000104169", "0001045810"}
        for r in selection(data, tier="A")
    )
    assert selection(data, limit=3) == selection(data)[:3]
    assert universe_hash() == universe_hash(deepcopy(data))


@pytest.mark.parametrize(
    "change", ["duplicate", "excluded_in_tier", "bad_format", "bad_status", "tier_a_only"]
)
def test_invalid_universe(change):
    data = universe()
    r = data["issuers"][0]
    if change == "duplicate":
        data["issuers"].append(deepcopy(r))
    elif change == "excluded_in_tier":
        r["status"] = "excluded"
        r["tier_b"] = True
    elif change == "bad_format":
        data["format"] = "wrong"
    elif change == "bad_status":
        r["status"] = "unknown"
    else:
        r["tier_a"] = True
        r["tier_b"] = False
    with pytest.raises(ValidationError):
        validate_universe(data)
