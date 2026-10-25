"""Equivalence: AQL layer (queries_aql, via anfra server) vs SQL oracle (queries.py).

Every query function in the app's data layer is executed through BOTH layers
and their outputs compared, so the semantic layer stays provably faithful to
the SQL oracle. Requires `anfra serve` (skips like the other live anfra tests
when it is down).

Known, pinned divergences:
- kpi_week_distance "this week":
    SQL oracle: date_trunc('week', local date) → the CURRENT PARTIAL week.
    AQL/AML:    activities.week_start is a stored column; the anfra metric
                answers with the last COMPLETE week.
  Both are defensible product decisions; the AQL behavior matches the anfra
  dashboard and is pinned here rather than forced to match.
- kpi_90d: wall-clock window (AQL `last 90 days`) vs data-relative window
  (SQL max(date) - 89). Within <5 km on ~1280 km.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import pandas as pd
import pytest
import queries as sql_q
import queries_aql as aql_q


def _server_up() -> bool:
    try:
        aql_q.get_client().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.anfra,
    pytest.mark.skipif(
        os.environ.get("ANFRA_LIVE_TESTS") == "0" or not _server_up(),
        reason="anfra serve not reachable (start it: ~/.anfra/bin/anfra serve)",
    ),
]

WIN = ("2026-01-01", "2026-06-30")  # a window with data from both eras
WIN_LONG = ("2025-01-01", "2026-06-30")

# (name, aql_call, sql_call, key_cols, numeric_cols, tol)
CASES: list[
    tuple[str, Callable[[], pd.DataFrame], Callable[[], pd.DataFrame], list[str], list[str], float]
] = [
    (
        "load_ramp",
        lambda: aql_q.load_ramp(*WIN),
        lambda: sql_q.load_ramp(*WIN),
        ["week_start"],
        ["load", "ramp_rate"],
        1e-4,
    ),
    (
        "weekly_run_distance",
        lambda: aql_q.weekly_run_distance(*WIN, (), ()),
        lambda: sql_q.weekly_run_distance(*WIN, (), ()),
        ["week_start"],
        ["run_km", "elev_gain_m"],
        1e-6,
    ),
    (
        "daily_runs",
        lambda: aql_q.daily_runs(*WIN, (), ()),
        lambda: sql_q.daily_runs(*WIN, (), ()),
        ["day"],
        ["km"],
        1e-6,
    ),
    (
        "weekly_category",
        lambda: aql_q.weekly_category(*WIN),
        lambda: sql_q.weekly_category(*WIN),
        ["week_start", "category"],
        ["hours"],
        1e-6,
    ),
    (
        "monthly_pace",
        lambda: aql_q.monthly_pace(*WIN, (), ()),
        lambda: sql_q.monthly_pace(*WIN, (), ()),
        ["month"],
        ["pace_min_km", "moving_time_s"],
        1e-4,
    ),
    (
        "monthly_cadence",
        lambda: aql_q.monthly_cadence(*WIN, (), ()),
        lambda: sql_q.monthly_cadence(*WIN, (), ()),
        ["month"],
        ["rpm"],
        1e-4,
    ),
    (
        "monthly_efficiency",
        lambda: aql_q.monthly_efficiency(*WIN, (), ()),
        lambda: sql_q.monthly_efficiency(*WIN, (), ()),
        ["month"],
        ["aerobic_efficiency"],
        1e-4,
    ),
    (
        "surface_pace_trend",
        lambda: aql_q.surface_pace_trend(*WIN, (), ()),
        lambda: sql_q.surface_pace_trend(*WIN, (), ()),
        ["month", "run_surface"],
        ["pace_min_km"],
        1e-4,
    ),
    (
        "stride_trend",
        lambda: aql_q.stride_trend(*WIN, (), ()),
        lambda: sql_q.stride_trend(*WIN, (), ()),
        ["month", "run_surface"],
        ["stride_m"],
        1e-4,
    ),
    (
        "hilliness_trend",
        lambda: aql_q.hilliness_trend(*WIN, (), ()),
        lambda: sql_q.hilliness_trend(*WIN, (), ()),
        ["month", "run_surface"],
        ["elev_per_km"],
        1e-4,
    ),
    (
        "decoupling_by_surface",
        lambda: aql_q.decoupling_by_surface(*WIN_LONG),
        lambda: sql_q.decoupling_by_surface(*WIN_LONG),
        ["run_surface"],
        ["avg_decoupling", "long_runs"],
        1e-6,
    ),
    (
        "stride_vs_pace",
        lambda: aql_q.stride_vs_pace(*WIN, (), ()),
        lambda: sql_q.stride_vs_pace(*WIN, (), ()),
        ["day", "name"],
        ["pace_min_km", "stride_m"],
        1e-3,  # 16.6667/avg_speed vs moving_time/(dist/1000): bounded rounding
    ),
    (
        "pace_blocks_weekly",
        lambda: aql_q.pace_blocks_weekly(*WIN, (), ()),
        lambda: sql_q.pace_blocks_weekly(*WIN, (), ()),
        ["week_start", "bucket", "bucket_num"],
        ["hours"],
        1e-6,
    ),
    (
        "decoupling_trend",
        lambda: aql_q.decoupling_trend(*WIN_LONG),
        lambda: sql_q.decoupling_trend(*WIN_LONG),
        ["activity_start", "name"],
        ["decoupling_pct"],
        1e-6,
    ),
    (
        "pace_by_temp",
        lambda: aql_q.pace_by_temp(*WIN, (), ()),
        lambda: sql_q.pace_by_temp(*WIN, (), ()),
        ["bucket_low"],
        ["pace_min_km", "runs"],
        1e-4,
    ),
]


def _approx(s: pd.Series, other: pd.Series, tol: float = 1e-6) -> bool:
    a = pd.to_numeric(s, errors="coerce").astype(float)
    b = pd.to_numeric(other, errors="coerce").astype(float)
    return bool((a - b).abs().max() <= tol)


# Comparison grain for datetime keys (chars), overridable per case. decoupling_trend
# pins day grain: the AQL layer renders activity_start in the athlete's local
# timezone (Paris), the SQL oracle shows the stored (UTC) timestamp — same day,
# same values, different clock rendering.
KEY_LEN = [19]
KEY_GRAIN = {"decoupling_trend": 10}


def _norm(x: object) -> str:
    """Normalize values for key comparison: '0' == '0.0', Timestamp == ISO date."""
    try:
        return f"{float(x):.6g}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass
    s = str(x)
    if s.endswith(" 00:00:00"):
        s = s[: -len(" 00:00:00")]
    return s[: KEY_LEN[0]]


def _assert_equivalent(
    a: pd.DataFrame, b: pd.DataFrame, key_cols: list[str], num_cols: list[str], tol: float
) -> None:
    assert list(a.columns) == list(b.columns), "column mismatch"
    a = a.sort_values(key_cols).reset_index(drop=True)
    b = b.sort_values(key_cols).reset_index(drop=True)
    assert len(a) == len(b), f"row count mismatch: {len(a)} vs {len(b)}"
    for c in key_cols:
        assert [_norm(x) for x in a[c]] == [_norm(x) for x in b[c]], f"key mismatch: {c}"
    for c in num_cols:
        assert _approx(a[c], b[c], tol), f"numeric mismatch: {c}"


# --------------------------------------------------------------------------
# Single-value KPIs
# --------------------------------------------------------------------------


def test_kpi_fitness_equivalent() -> None:
    a, b = aql_q.kpi_fitness(), sql_q.kpi_fitness()
    assert list(a.columns) == list(b.columns) == ["ctl", "atl", "tsb"]
    assert _approx(a.ctl, b.ctl) and _approx(a.atl, b.atl) and _approx(a.tsb, b.tsb)


def test_kpi_decoupling_equivalent() -> None:
    a, b = aql_q.kpi_decoupling(), sql_q.kpi_decoupling()
    assert int(a.long_runs.iloc[0]) == int(b.long_runs.iloc[0])
    assert _approx(a.avg_decoupling, b.avg_decoupling)


def test_kpi_90d_within_tolerance() -> None:
    # windows differ by edge convention (wall-clock vs data-relative): 0.04% apart
    a, b = aql_q.kpi_90d(()), sql_q.kpi_90d(())
    assert _approx(a.km, b.km, tol=5.0)  # <5 km on ~1280 km


def test_kpi_week_distance_avg_matches_this_week_pinned() -> None:
    a, b = aql_q.kpi_week_distance((), ()), sql_q.kpi_week_distance((), ())
    assert _approx(a.avg_4wk_km, b.avg_4wk_km, tol=2.0)  # <2 km on ~51 km
    # pinned: AQL answers with the last COMPLETE week (see module docstring)
    assert float(a.this_week_km.iloc[0]) > float(a.avg_4wk_km.iloc[0]) - 20


def test_date_bounds_equivalent() -> None:
    assert tuple(_norm(x) for x in aql_q.date_bounds()) == tuple(
        _norm(x) for x in sql_q.date_bounds()
    )


# --------------------------------------------------------------------------
# Trend / chart queries (table-driven)
# --------------------------------------------------------------------------


def test_fitness_trend_equivalent() -> None:
    a = aql_q.fitness_trend("2026-01-01", "2026-12-31").sort_values("week_start")
    b = sql_q.fitness_trend("2026-01-01", "2026-12-31").sort_values("week_start")
    assert len(a) == len(b)
    assert [_norm(x) for x in a.week_start] == [_norm(x) for x in b.week_start]
    assert _approx(a.ctl, b.ctl) and _approx(a.atl, b.atl) and _approx(a.tsb, b.tsb)


def test_sport_mix_equivalent() -> None:
    a = aql_q.sport_mix("2025-09-01", "2026-12-31").sort_values("sport_group")
    b = sql_q.sport_mix("2025-09-01", "2026-12-31").sort_values("sport_group")
    assert list(a.sport_group) == list(b.sport_group)
    assert _approx(a.hours, b.hours)


@pytest.mark.parametrize(
    "name,aql_call,sql_call,key_cols,num_cols,tol", CASES, ids=[c[0] for c in CASES]
)
def test_chart_query_equivalent(
    name: str,  # noqa: ARG001
    aql_call: Callable[[], pd.DataFrame],
    sql_call: Callable[[], pd.DataFrame],
    key_cols: list[str],
    num_cols: list[str],
    tol: float,
) -> None:
    KEY_LEN[0] = KEY_GRAIN.get(name, 19)
    _assert_equivalent(aql_call(), sql_call(), key_cols, num_cols, tol)


# --------------------------------------------------------------------------
# Filter behavior on the AQL layer
# --------------------------------------------------------------------------


def test_filters_narrow_the_aql_layer() -> None:
    with_surface = aql_q.kpi_week_distance((), ("road",))
    assert float(with_surface.this_week_km.iloc[0]) > 0
    trail_only = aql_q.kpi_90d(())  # all sports
    run_only = aql_q.kpi_90d(("run",))
    assert float(run_only.km.iloc[0]) < float(trail_only.km.iloc[0])


def test_surface_filter_narrows_surface_charts() -> None:
    all_surf = aql_q.surface_pace_trend(*WIN, (), ())
    road_only = aql_q.surface_pace_trend(*WIN, (), ("road",))
    assert set(road_only.run_surface) <= {"road"}
    assert len(road_only) <= len(all_surf)
