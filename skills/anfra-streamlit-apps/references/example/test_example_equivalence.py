"""Equivalence gate template: oracle ≡ live layer.

Lives in tests/integration/, marked like the repo's other live MCP suites.
Three windows — 90-day default, all-time, empty — over every data function.
ADAPT: module names and, if your grains differ, the key columns used for the
deterministic sort.
"""

from __future__ import annotations

import datetime as dt
import os

import example_data_aql as aql
import pandas as pd
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.anfra]


@pytest.fixture(scope="module", autouse=True)
def _require_server() -> None:
    if os.environ.get("ANFRA_LIVE_TESTS") == "0":
        pytest.skip("live tests disabled (ANFRA_LIVE_TESTS=0)")
    try:
        if not aql.get_client().ping():
            pytest.skip("anfra serve not reachable")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"anfra serve not reachable: {exc}")


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize for comparison: numerics → float64 (int/float and
    Arrow-backed dtypes differ across layers); everything else (objects,
    Arrow strings, Timestamps) → day-grain strings."""
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = pd.to_numeric(df[col]).astype("float64")
        else:
            df[col] = df[col].astype(str).str.slice(0, 10)
    return df


def _assert_equivalent(
    name: str,
    oracle_df: pd.DataFrame,
    live_df: pd.DataFrame,
    key_cols: list[str],
    num_cols: list[str],
) -> None:
    """Sort by keys + numerics BEFORE comparing — duplicate natural keys
    (two same-day same-name activities) otherwise pair non-deterministically."""
    assert list(oracle_df.columns) == list(live_df.columns), f"{name}: columns differ"
    o = _norm(oracle_df).sort_values(key_cols + num_cols).reset_index(drop=True)
    v = _norm(live_df).sort_values(key_cols + num_cols).reset_index(drop=True)
    assert len(o) == len(v), f"{name}: row count {len(o)} vs {len(v)}"
    pd.testing.assert_frame_equal(o, v, check_exact=False, rtol=1e-6, atol=1e-9)


@pytest.fixture(scope="module")
def windows() -> dict[str, tuple[str, str]]:
    lo, hi = aql.date_bounds()
    return {
        "90d": (str(hi - dt.timedelta(days=89)), str(hi)),
        "all": (str(lo), str(hi)),
        "empty": ("2013-01-01", "2013-03-01"),
    }


def test_date_bounds(example_oracle) -> None:  # noqa: ANN001
    assert example_oracle.date_bounds() == aql.date_bounds()


def test_kpi_totals(example_oracle, windows) -> None:  # noqa: ANN001
    for win, (frm, to) in windows.items():
        _assert_equivalent(
            f"kpi_totals[{win}]",
            example_oracle.kpi_totals(frm, to, ()),
            aql.kpi_totals(frm, to, ()),
            [],
            ["km", "runs"],
        )


def test_weekly_distance(example_oracle, windows) -> None:  # noqa: ANN001
    for win, (frm, to) in windows.items():
        for surfaces in ((), ("road",)):
            _assert_equivalent(
                f"weekly_distance[{win}, surfaces={surfaces or 'all'}]",
                example_oracle.weekly_distance(frm, to, surfaces),
                aql.weekly_distance(frm, to, surfaces),
                ["week_start"],
                ["km"],
            )


def test_mix_by_surface(example_oracle, windows) -> None:  # noqa: ANN001
    for win, (frm, to) in windows.items():
        _assert_equivalent(
            f"mix_by_surface[{win}]",
            example_oracle.mix_by_surface(frm, to),
            aql.mix_by_surface(frm, to),
            ["run_surface"],
            ["hours"],
        )
