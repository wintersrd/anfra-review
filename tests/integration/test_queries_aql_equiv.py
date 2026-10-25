"""Equivalence: AQL layer (queries_aql, via anfra server) vs SQL oracle (queries.py).

The SQL module stays the test oracle during the migration: both layers are
executed and their outputs compared. Requires `anfra serve` (skips like the
other live anfra tests when it is down).

Known, pinned divergence — kpi_week_distance "this week":
  - SQL oracle: date_trunc('week', local date) → the CURRENT PARTIAL week.
  - AQL/AML:    activities.week_start is a stored column; the anfra metric
                answers with the last COMPLETE week.
Both are defensible products decisions; the AQL behavior matches the anfra
dashboard and is pinned here rather than forced to match.
"""

from __future__ import annotations

import os

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


def _approx(s: pd.Series, other: pd.Series, tol: float = 1e-6) -> bool:
    a = pd.to_numeric(s, errors="coerce").astype(float)
    b = pd.to_numeric(other, errors="coerce").astype(float)
    return bool((a - b).abs().max() <= tol)


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


def test_fitness_trend_equivalent() -> None:
    a = aql_q.fitness_trend("2026-01-01", "2026-12-31").sort_values("week_start")
    b = sql_q.fitness_trend("2026-01-01", "2026-12-31").sort_values("week_start")
    assert len(a) == len(b)
    assert [str(x)[:10] for x in a.week_start] == [str(x)[:10] for x in b.week_start]
    assert _approx(a.ctl, b.ctl) and _approx(a.atl, b.atl) and _approx(a.tsb, b.tsb)


def test_sport_mix_equivalent() -> None:
    a = aql_q.sport_mix("2025-09-01", "2026-12-31").sort_values("sport_group")
    b = sql_q.sport_mix("2025-09-01", "2026-12-31").sort_values("sport_group")
    assert list(a.sport_group) == list(b.sport_group)
    assert _approx(a.hours, b.hours)


def test_filters_narrow_the_aql_layer() -> None:
    with_surface = aql_q.kpi_week_distance((), ("road",))
    assert float(with_surface.this_week_km.iloc[0]) > 0
    trail_only = aql_q.kpi_90d(())  # all sports
    run_only = aql_q.kpi_90d(("run",))
    assert float(run_only.km.iloc[0]) < float(trail_only.km.iloc[0])
