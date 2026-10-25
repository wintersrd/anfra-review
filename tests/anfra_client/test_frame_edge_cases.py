"""DataFrame edge cases for anfra_client result handling — offline, mock-free.

Constructs QueryResults directly (the shapes mirror recorded MCP responses)
and pins how the frame layer behaves on messy-but-realistic payloads:
numeric-string coercion, nulls, non-numeric columns that look numeric,
integer db_types, ragged rows, empty results, unicode round-trips, and
Filter payload typing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from anfra_client import Filter
from anfra_client.errors import AnfraContractError
from anfra_client.models import Column, QueryResult

NUM = Column(
    name="km",
    field_name="run_distance_km",
    db_type="DOUBLE",
    is_measure=True,
)
INT = Column(
    name="runs",
    field_name="run_activities",
    db_type="BIGINT",
    is_measure=True,
)
TEXT = Column(
    name="sport",
    field_name="activities.sport_group",
    db_type="VARCHAR",
)


def _result(
    records: list[list],
    columns: tuple[Column, ...] = (TEXT, NUM),
    fields: list[str] | None = None,
) -> QueryResult:
    return QueryResult(
        fields=fields or [c.name for c in columns],
        records=records,
        columns=columns,
        sql="SELECT 1",
        has_more=False,
    )


# --------------------------------------------------------------------------
# frame() coercion
# --------------------------------------------------------------------------


def test_numeric_strings_coerce_to_float() -> None:
    df = _result([["run", "12.5"], ["ride", "0"]]).frame()
    assert df["km"].dtype.kind == "f"
    assert df["km"].tolist() == [12.5, 0.0]


def test_nulls_become_nan_in_numeric_column() -> None:
    df = _result([["run", None], ["ride", "3.25"]]).frame()
    assert pd.isna(df["km"].iloc[0])
    assert df["km"].iloc[1] == 3.25


def test_integer_db_type_becomes_nullable_int() -> None:
    df = _result([["run", "12"]], columns=(TEXT, INT)).frame()
    assert str(df["runs"].dtype) == "Int64"
    assert df["runs"].iloc[0] == 12


def test_non_numeric_column_stays_uncoerced_even_if_values_look_numeric() -> None:
    # a VARCHAR column carrying numeric-looking strings must NOT be coerced
    text_num = Column(
        name="week",
        field_name="activities.week_start",
        db_type="VARCHAR",
    )
    df = _result([["2026-01-05"], ["2026-01-12"]], columns=(text_num,)).frame()
    assert not pd.api.types.is_numeric_dtype(df["week"])
    assert df["week"].tolist() == ["2026-01-05", "2026-01-12"]


def test_coerce_false_keeps_raw_strings() -> None:
    df = _result([["run", "12.5"]]).frame(coerce=False)
    assert df["km"].iloc[0] == "12.5"


# --------------------------------------------------------------------------
# rows / structural edges
# --------------------------------------------------------------------------


def test_rows_zip_fields_in_order() -> None:
    res = _result([["run", "5"]])
    assert res.rows == [{"sport": "run", "km": "5"}]


def test_ragged_row_does_not_crash() -> None:
    # records longer than fields are tolerated (strict=False) and truncated
    res = _result([["run", "5", "extra"]])
    assert res.rows[0] == {"sport": "run", "km": "5"}


def test_empty_records_frame_has_columns() -> None:
    df = _result([]).frame()
    assert len(df) == 0
    assert list(df.columns) == ["sport", "km"]


def test_unicode_and_control_chars_round_trip() -> None:
    res = _result([["Zwift\u0002Race", "4.75"]])
    assert res.rows[0]["sport"] == "Zwift\u0002Race"
    assert res.frame().iloc[0]["sport"] == "Zwift\u0002Race"


def test_none_vs_empty_string_distinct() -> None:
    res = _result([[None, ""], ["", None]])
    assert res.rows[0]["sport"] is None and res.rows[0]["km"] == ""
    assert res.rows[1]["sport"] == "" and res.rows[1]["km"] is None


def test_has_more_and_timings_survive() -> None:
    res = QueryResult(
        fields=["sport"],
        records=[["run"]],
        columns=(TEXT,),
        has_more=True,
        timings={"end_ms": 204},
    )
    assert res.has_more is True and res.timings["end_ms"] == 204


def test_missing_result_keys_is_contract_error() -> None:
    # envelope regression tripwire: a success payload without result.fields
    from anfra_client.client import AnfraClient

    inner = {"sql": "SELECT 1", "aql": "explore {}", "columns": []}
    with pytest.raises(AnfraContractError):
        AnfraClient._result_from(inner)


# --------------------------------------------------------------------------
# Filter payload typing
# --------------------------------------------------------------------------


def test_filter_stringifies_scalars_keeps_bools() -> None:
    f = Filter(field="a.b", operator="is", values=[1, 4.5, True, False, "x"])
    payload = f.to_payload()
    assert payload["values"] == ["1", "4.5", True, False, "x"]


def test_is_in_builder_rejects_empty_values() -> None:
    from anfra_client import is_in

    with pytest.raises(ValueError, match="at least one"):
        is_in("a.b", [])


def test_between_passes_values_through_server_validates() -> None:
    # no client-side arity guard: the server rejects malformed 'between'
    payload = Filter(
        field="a.b", operator="between", values=["2026-01-01", "2026-02-01"]
    ).to_payload()
    assert payload["values"] == ["2026-01-01", "2026-02-01"]
