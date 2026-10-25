"""Filter builders → MCP payload shapes (the contract regression net)."""

from __future__ import annotations

import pytest

from anfra_client import between, condition, equals, is_in, last
from anfra_client.models import Condition, Filter


def test_is_in_payload_stringifies_numbers():
    f = is_in("activities.sport_group", ["run", "ride"])
    assert f.to_payload() == {
        "field": "activities.sport_group",
        "operator": "is",
        "values": ["run", "ride"],
    }
    f2 = is_in("m.count", [90, 120])
    assert f2.to_payload()["values"] == ["90", "120"]  # JSON numbers refused by server


def test_is_in_rejects_empty():
    with pytest.raises(ValueError, match="at least one"):
        is_in("activities.sport_group", [])


def test_equals_is_single_is_in():
    assert equals("activities.is_race", True).to_payload() == {
        "field": "activities.is_race",
        "operator": "is",
        "values": [True],  # booleans stay bool per schema
    }


def test_between_payload():
    f = between("activities.date", "2026-01-01", "2026-08-31")
    assert f.to_payload() == {
        "field": "activities.date",
        "operator": "between",
        "values": ["2026-01-01", "2026-08-31"],
    }


def test_last_payload_carries_modifier():
    f = last("activities.date", 90, unit="day")
    assert f.to_payload() == {
        "field": "activities.date",
        "operator": "last",
        "values": ["90"],
        "modifier": "day",
    }


def test_last_rejects_nonpositive():
    with pytest.raises(ValueError, match="n >= 1"):
        last("activities.date", 0)


def test_condition_payload():
    assert condition("activities.is_race").to_payload() == {"expr": "activities.is_race"}
    with pytest.raises(ValueError, match="non-empty"):
        condition("  ")


def test_dataclasses_are_the_low_level_escape_hatch():
    raw = Filter(field="x.y", operator="contains", values=("abc",))
    assert raw.to_payload()["operator"] == "contains"
    assert isinstance(condition("a.b"), Condition)
