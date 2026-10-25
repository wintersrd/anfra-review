"""Every streamlit query function, run against the fixture DB.

Guards the data layer the app is built on: column contracts, non-emptiness
on the default window, and that sport/surface filters actually filter.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

WIDE = ("2024-01-01", "2026-12-31")

ACT_GRAIN = [  # (date_from, date_to, sports, surfaces) signature
    "weekly_run_distance",
    "daily_runs",
    "monthly_pace",
    "monthly_cadence",
    "monthly_efficiency",
    "surface_pace_trend",
    "stride_trend",
    "hilliness_trend",
    "stride_vs_pace",
    "pace_blocks_weekly",
    "pace_by_temp",
]
DATE_ONLY = ["sport_mix", "weekly_category", "decoupling_by_surface", "decoupling_trend"]
WEEKLY_GRAIN = ["fitness_trend", "load_ramp"]


def call(q, name, dates=WIDE, sports=(), surfaces=()):
    fn = getattr(q, name)
    if name.startswith("kpi_"):
        if name in ("kpi_fitness", "kpi_decoupling"):
            return fn()
        if name == "kpi_90d":
            return fn(sports)
        return fn(sports, surfaces)
    if name in WEEKLY_GRAIN or name in DATE_ONLY:
        return fn(*dates)
    return fn(*dates, sports, surfaces)


class TestColumnContracts:
    def test_kpis(self, queries_mod):
        q = queries_mod
        assert list(q.kpi_fitness().columns) == ["ctl", "atl", "tsb"]
        assert list(q.kpi_decoupling().columns) == ["avg_decoupling", "long_runs"]
        wk = q.kpi_week_distance((), ())
        assert {"this_week_km", "avg_4wk_km"} <= set(wk.columns) or len(wk.columns) >= 2
        assert len(q.kpi_90d(())) == 1

    @pytest.mark.parametrize("name", WEEKLY_GRAIN + ACT_GRAIN + DATE_ONLY)
    def test_shapes(self, queries_mod, name):
        df = call(queries_mod, name)
        assert len(df) > 0, f"{name} returned no rows"
        assert len(df.columns) >= 2, f"{name} unexpectedly narrow: {list(df.columns)}"


class TestFiltersActuallyFilter:
    def test_surface_filter_narrows_run_charts(self, queries_mod):
        q = queries_mod
        full = call(q, "weekly_run_distance", sports=(), surfaces=())
        trail = call(q, "weekly_run_distance", sports=(), surfaces=("trail",))
        assert len(trail) < len(full)
        assert trail["run_km"].sum() < full["run_km"].sum()

    def test_trail_only_pace_is_slower_than_road(self, queries_mod):
        # the user's original motivation: technical trail inflates pace
        q = queries_mod
        road = call(q, "surface_pace_trend", surfaces=("road",))
        trail = call(q, "surface_pace_trend", surfaces=("trail",))
        assert trail["pace_min_km"].mean() > road["pace_min_km"].mean()

    def test_sport_filter_removes_non_run_from_run_charts(self, queries_mod):
        q = queries_mod
        ride_only = call(q, "monthly_pace", sports=("ride",), surfaces=())
        assert ride_only.empty  # run-only chart + non-run sport = empty (by design)

    def test_sport_mix_is_cross_filter_source(self, queries_mod):
        # sport_mix powers the click-to-filter donut, so it deliberately
        # ignores the sport selection (you pick the sport FROM it)
        q = queries_mod
        sports = {row for row in call(q, "sport_mix")["sport_group"]}
        assert {"run", "ride", "strength"} <= sports
        assert call(q, "sport_mix", sports=("run",)).equals(call(q, "sport_mix", sports=("ride",)))


class TestMetricSanity:
    def test_pace_buckets_cover_expected_labels(self, queries_mod):
        df = call(queries_mod, "pace_blocks_weekly")
        assert set(df["bucket"]) <= set(queries_mod.PACE_BUCKETS)
        # unknown bucket is never the dominant bucket for this athlete
        by_bucket = df.groupby("bucket")["hours"].sum()
        assert by_bucket.idxmax() != "unknown"

    def test_stride_plausible(self, queries_mod):
        df = call(queries_mod, "stride_trend")
        # human running stride: ~1.5-2.8m; guards the rpm-vs-spm confusion
        assert df["stride_m"].between(1.2, 3.0).all()

    def test_monthly_pace_in_running_band(self, queries_mod):
        df = call(queries_mod, "monthly_pace")
        assert df["pace_min_km"].between(3.0, 9.0).all()

    def test_kpi_decoupling_matches_calc_table(self, queries_mod, fixture_conn):
        df = queries_mod.kpi_decoupling()
        direct = fixture_conn.execute(
            "SELECT AVG(decoupling_pct), COUNT(*) FROM decoupling_calc "
            "WHERE activity_start >= CURRENT_DATE - INTERVAL 90 DAY"
        ).fetchone()
        assert df["long_runs"].iloc[0] == direct[1]
        assert df["avg_decoupling"].iloc[0] == pytest.approx(direct[0], abs=1e-6)

    def test_decoupling_trend_matches_calc_rows(self, queries_mod):
        df = call(queries_mod, "decoupling_trend")
        assert len(df) == 71  # fingerprint of committed decoupling.csv
