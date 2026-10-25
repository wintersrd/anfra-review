"""Logical query elements and result types.

The query-side types (:class:`Filter`, :class:`Condition`) model anfra's
``core.query`` ``input`` schema; the result-side types wrap its response into
row-dicts and (optionally) a pandas DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Query elements
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Filter:
    """A structured filter, ANDed with the query's own filters by the server.

    ``values`` follow anfra's typing rules: numbers are sent as *strings* in
    JSON number syntax (the server rejects JSON numbers to avoid precision
    loss), booleans as bools, dates/text as strings. :func:`anfra_client.filters`
    helpers handle that conversion for you.

    Validated operator set (against anfra 0.13.3): ``is`` (IN-list, >=1 value),
    ``between`` (2 values), ``last`` (1 value + ``modifier`` date unit).
    Other operators (``contains``, ``is_not``, ...) exist but are unvalidated
    by this client's live test-suite — use at your own risk.
    """

    field: str
    operator: str
    values: tuple[str | int | float | bool, ...]
    modifier: str | None = None
    aggregation: str | None = None

    def to_payload(self) -> dict:
        payload: dict = {
            "field": self.field,
            "operator": self.operator,
            "values": [v if isinstance(v, bool) else str(v) for v in self.values],
        }
        if self.modifier is not None:
            payload["modifier"] = self.modifier
        if self.aggregation is not None:
            payload["aggregation"] = self.aggregation
        return payload


@dataclass(frozen=True)
class Condition:
    """A free-form AQL condition expression, e.g.

    ``activities.date matches @(last 90 days)`` or
    ``activities.sport_group in ['run', 'trail']``.
    """

    expr: str

    def to_payload(self) -> dict:
        return {"expr": self.expr}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

_FLOAT_DB_TYPES = {"DOUBLE", "REAL", "FLOAT", "DECIMAL", "HUGEINT", "numeric"}
_INT_DB_TYPES = {"BIGINT", "INTEGER", "SMALLINT", "TINYINT", "int"}


@dataclass(frozen=True)
class Column:
    """One result column's metadata, from ``core.query``'s ``columns[]``."""

    name: str
    field_name: str
    label: str = ""
    type: str = ""
    db_type: str = ""
    semantic_type: str = ""
    is_measure: bool = False

    @classmethod
    def from_raw(cls, raw: dict) -> Column:
        return cls(
            name=str(raw.get("name", "")),
            field_name=str(raw.get("fieldName", raw.get("name", ""))),
            label=str(raw.get("label", "")),
            type=str(raw.get("arrow_type", {}).get("type", raw.get("type", ""))),
            db_type=str(raw.get("db_type", "")),
            semantic_type=str(raw.get("semantic_type", "")),
            is_measure=bool(raw.get("isMeasure", False)),
        )

    @property
    def is_numeric(self) -> bool:
        t = (self.db_type or self.type).upper()
        return any(marker in t for marker in _FLOAT_DB_TYPES) or any(
            marker in t for marker in _INT_DB_TYPES
        )

    @property
    def is_float(self) -> bool:
        t = (self.db_type or self.type).upper()
        return any(marker in t for marker in _FLOAT_DB_TYPES)


@dataclass(frozen=True)
class QueryResult:
    """A successful query: typed columns plus row records (arrays, field order).

    ``rows`` zips ``fields`` and ``records`` into dicts — the usual access
    path. Numeric cells arrive as strings over the wire; :meth:`frame`
    coerces them using the column metadata.
    """

    fields: list[str]
    records: list[list]
    columns: tuple[Column, ...] = ()
    sql: str | None = None
    aql: str | None = None
    has_more: bool = False
    timings: dict = field(default_factory=dict)
    request_id: str | None = None

    @property
    def rows(self) -> list[dict]:
        return [dict(zip(self.fields, rec, strict=False)) for rec in self.records]

    def __len__(self) -> int:
        return len(self.records)

    def frame(self, *, coerce: bool = True):  # type: ignore[no-untyped-def]
        """Return a ``pandas.DataFrame``; numeric string cells become floats/ints."""
        import pandas as pd

        df = pd.DataFrame(self.records, columns=self.fields)
        if coerce:
            for col in self.columns:
                # match on the RESULT column name (col.name == fields[] entries);
                # col.field_name is the source model field, not a result key
                if col.name in df.columns and col.is_numeric:
                    df[col.name] = pd.to_numeric(df[col.name], errors="coerce")
                    if not col.is_float:
                        df[col.name] = df[col.name].astype("Int64")
        return df
