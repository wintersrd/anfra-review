"""Builder helpers for logical query elements.

These turn Python values into anfra-typed :class:`~anfra_client.models.Filter`
/:class:`~anfra_client.models.Condition` payloads (stringifying numbers as the
MCP schema requires, attaching date-unit modifiers, ...).
"""

from __future__ import annotations

from anfra_client.models import Condition, Filter

__all__ = ["is_in", "equals", "between", "last", "condition"]


def is_in(field: str, values: list) -> Filter:
    """``field is one of values`` — anfra's ``is`` operator is an IN-list.

    ``values`` items are numbers/dates/text; they are stringified per the
    schema (a JSON number is refused server-side).
    """
    if not values:
        raise ValueError("is_in() requires at least one value (server rejects empty 'is')")
    return Filter(field=field, operator="is", values=tuple(values))


def equals(field: str, value: str | int | float) -> Filter:
    """Single-value convenience for :func:`is_in`."""
    return is_in(field, [value])


def between(field: str, low: str | int | float, high: str | int | float) -> Filter:
    """Inclusive range filter — validated for date fields (``YYYY-MM-DD``)."""
    return Filter(field=field, operator="between", values=(low, high))


def last(field: str, n: int, unit: str = "day") -> Filter:
    """Relative window: ``last N <unit>`` — validated with ``unit='day'``."""
    if n < 1:
        raise ValueError("last() requires n >= 1")
    return Filter(field=field, operator="last", values=(n,), modifier=unit)


def condition(expr: str) -> Condition:
    """Free-form AQL condition, e.g. ``condition("activities.is_race")``.

    Use when no structured operator fits; the server compiles these with the
    same diagnostics as query text.
    """
    if not expr.strip():
        raise ValueError("condition() requires a non-empty AQL expression")
    return Condition(expr=expr)
