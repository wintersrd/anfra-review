"""Oracle integration tests: cycling_queries vs the fixture DuckDB.

The fixture DB is built from the committed data/raw CSVs by conftest, so all
pinned numbers below are fingerprints of the committed data — update them in
the same commit as any deliberate re-sync (AGENTS.md rule 6).
"""

from __future__ import annotations

import datetime as dt

import cycling_queries as oracle
import pandas as pd
import pytest

pytestmark = pytest.mark.integration

DEFAULT_FROM = "2026-07-08"  # latest ride − 89 d (§6.2 data-relative default)
DEFAULT_TO = "2026-10-15"
EMPTY = ("2011-01-01", "2011-02-01")


@pytest.fixture()
def cyc(fixture_conn, monkeypatch):
    """Oracle wired to the fixture DB (bypasses the streamlit resource cache)."""
    monkeypatch.setattr(oracle, "get_conn", lambda: fixture_conn)
    oracle.date_bounds.clear()
    oracle.kpi_ftp.clear()
    oracle.kpi_ride_km_week.clear()
    oracle.kpi_elev_90d.clear()
    oracle.kpi_if_90d.clear()
    return oracle


class TestMetadataAndKpis:
    def test_date_bounds_are_dates_over_rides(self, cyc):
        lo, hi = cyc.date_bounds()
        assert (lo, hi) == (dt.date(2024, 10, 5), dt.date(2026, 10, 15))
        assert isinstance(lo, dt.date)

    def test_kpi_ftp_current(self, cyc):
        assert float(cyc.kpi_ftp().iloc[0]["ftp_w"]) == 250.0

    def test_kpi_week_distance_exact_definition(self, cyc):
        # today 2026-10-26 (Mon): current week has no rides yet; the four
        # complete weeks 09-28..10-19 sum 12.08417 + 77.65245 + 29.07361 + 0.
        row = cyc.kpi_ride_km_week((), dt.date(2026, 10, 26)).iloc[0]
        assert row["this_week_km"] == 0.0
        assert row["avg_4wk_km"] == pytest.approx((12.08417 + 77.65245 + 29.07361) / 4)

    def test_kpi_elev_90d_wall_clock(self, cyc):
        row = cyc.kpi_elev_90d((), dt.date(2026, 10, 26)).iloc[0]
        assert row["elev_gain_m"] == 5665.0
        assert row["km"] == pytest.approx(498.61616)

    def test_kpi_if_90d_weighted(self, cyc):
        row = cyc.kpi_if_90d((), dt.date(2026, 10, 26)).iloc[0]
        assert row["if_mean"] == pytest.approx(0.759078393512861)
        assert row["rides_with_power"] == 10

    def test_kpi_if_90d_null_when_no_power(self, cyc):
        row = cyc.kpi_if_90d((), dt.date(2011, 1, 1)).iloc[0]
        assert pd.isna(row["if_mean"]) and row["rides_with_power"] == 0


class TestWeeklyGrain:
    def test_fitness_trend_full_history_to_window_end(self, cyc):
        df = cyc.fitness_trend(DEFAULT_FROM, DEFAULT_TO)
        assert len(df) == 771  # 772 weeks minus the week after date_to
        assert df["week_start"].is_monotonic_increasing
        assert str(df["week_start"].iloc[0])[:10] == "2012-01-09"

    def test_load_ramp_first_week_gap(self, cyc):
        df = cyc.weekly_load_ramp(DEFAULT_FROM, DEFAULT_TO)
        assert len(df) == 14
        assert pd.isna(df["ramp"].iloc[0])
        assert df["ramp"].iloc[1] == pytest.approx(df["load"].iloc[1] - df["load"].iloc[0])
        assert (df["load"] >= 0).all()  # zero-load ride weeks are data, not errors

    def test_volume_family(self, cyc):
        wr = cyc.weekly_ride_distance(*EMPTY)
        cal = cyc.ride_calendar(*EMPTY)
        wh = cyc.weekly_hours_by_type(*EMPTY)
        assert len(wr) == 0 and len(cal) == 0 and len(wh) == 0

    def test_weekly_distance_window_sum(self, cyc):
        wr = cyc.weekly_ride_distance(DEFAULT_FROM, DEFAULT_TO)
        assert len(wr) == 11
        assert wr["ride_km"].sum() == pytest.approx(520.6177, abs=1e-3)


class TestVolumeMix:
    def test_ride_mix_default(self, cyc):
        df = cyc.ride_mix(DEFAULT_FROM, DEFAULT_TO)
        by = dict(zip(df["ride_type"], df["hours"], strict=True))
        assert by["road"] == pytest.approx(20.98722, abs=1e-4)
        assert by["virtual"] == pytest.approx(7.1525, abs=1e-4)
        assert by["mtb"] == pytest.approx(6.855, abs=1e-4)


class TestPower:
    def test_rides_with_power_counts(self, cyc):
        row = cyc.rides_with_power(DEFAULT_FROM, DEFAULT_TO, ()).iloc[0]
        assert (row["with_power"], row["total"]) == (10, 34)

    def test_power_zones_labels_and_hours(self, cyc):
        df = cyc.power_zones_weekly(DEFAULT_FROM, DEFAULT_TO, ())
        assert set(df["zone"]) <= set(oracle.FTP_ZONE_LABELS)
        # zone hours must sum to total moving hours of power rides
        pw_hours = cyc.rides_with_power(DEFAULT_FROM, DEFAULT_TO, ())
        assert df["hours"].sum() > 0
        assert pw_hours.iloc[0]["with_power"] == 10

    def test_intensity_if_and_pctftp_consistent(self, cyc):
        df = cyc.intensity_trend(DEFAULT_FROM, DEFAULT_TO, ())
        for _, row in df.iterrows():
            assert row["if_mean"] * 100 == pytest.approx(row["pct_ftp"], abs=1e-6)

    def test_power_weight_weekly(self, cyc):
        df = cyc.power_weight_weekly(DEFAULT_FROM, DEFAULT_TO, ())
        assert len(df) == 11
        valid = df["watts"].dropna()
        assert (valid > 100).all()
        assert len(valid) == 6  # 5 weeks in window have no power rides → gaps
        assert df["w_per_kg"].dropna().gt(1).all()
        # wherever watts is null (no power rides), W/kg must be null too
        assert df.loc[df["watts"].isna(), "w_per_kg"].isna().all()

    def test_power_family_empty(self, cyc):
        assert len(cyc.power_zones_weekly(*EMPTY, ())) == 0
        assert len(cyc.intensity_trend(*EMPTY, ())) == 0
        assert len(cyc.power_weight_weekly(*EMPTY, ())) == 0


class TestSpeedCadence:
    def test_speed_monthly_road_faster_than_mtb(self, cyc):
        df = cyc.speed_by_type_monthly(DEFAULT_FROM, DEFAULT_TO, ())
        road = df[df["ride_type"] == "road"]["speed_kmh"].mean()
        mtb = df[df["ride_type"] == "mtb"]["speed_kmh"].mean()
        assert road > mtb

    def test_cadence_guard_and_weighting(self, cyc):
        df = cyc.cadence_by_type_monthly(DEFAULT_FROM, DEFAULT_TO, ())
        assert ((df["rpm"] > 60) & (df["rpm"] < 110)).all()

    def test_cadence_buckets(self, cyc):
        df = cyc.cadence_buckets_weekly(DEFAULT_FROM, DEFAULT_TO, ())
        assert set(df["bucket"]) <= set(oracle.CADENCE_BUCKETS)
        assert len(df) == 7

    def test_scatter_only_qualifying_rides(self, cyc):
        df = cyc.cadence_vs_speed(DEFAULT_FROM, DEFAULT_TO, ())
        assert len(df) == 4
        assert (df["cadence"] > 40).all()
        assert list(df.columns) == ["day", "name", "ride_type", "speed_kmh", "cadence"]

    def test_hilliness_range(self, cyc):
        df = cyc.hilliness_by_type_monthly(DEFAULT_FROM, DEFAULT_TO, ())
        assert ((df["elev_per_km"] > 0) & (df["elev_per_km"] < 100)).all()

    def test_speed_by_temp_buckets(self, cyc):
        df = cyc.speed_by_temp(DEFAULT_FROM, DEFAULT_TO, ())
        assert (df["bucket_low"] >= -5).all()
        assert ((df["bucket_low"] / 5) == (df["bucket_low"] // 5)).all()  # multiples of 5
        assert df["rides"].sum() == 27

    def test_speed_family_narrowed_to_mtb(self, cyc):
        df = cyc.speed_by_type_monthly(DEFAULT_FROM, DEFAULT_TO, ("mtb",))
        assert set(df["ride_type"]) == {"mtb"}

    def test_speed_family_empty(self, cyc):
        assert len(cyc.speed_by_type_monthly(*EMPTY, ())) == 0
        assert len(cyc.cadence_by_type_monthly(*EMPTY, ())) == 0
        assert len(cyc.cadence_buckets_weekly(*EMPTY, ())) == 0
        assert len(cyc.cadence_vs_speed(*EMPTY, ())) == 0
        assert len(cyc.hilliness_by_type_monthly(*EMPTY, ())) == 0
        assert len(cyc.speed_by_temp(*EMPTY, ())) == 0


class TestEndurance:
    def test_long_ride_decoupling_rows(self, cyc):
        df = cyc.long_ride_decoupling(DEFAULT_FROM, DEFAULT_TO)
        assert len(df) == 6
        assert df["decoupling_pct"].notna().all()
        assert df["day"].is_monotonic_increasing

    def test_decoupling_by_type(self, cyc):
        df = cyc.decoupling_by_type(DEFAULT_FROM, DEFAULT_TO)
        assert df["long_rides"].sum() == 6
        assert set(df["ride_type"]) <= set(oracle.RIDE_TYPES)

    def test_endurance_empty(self, cyc):
        assert len(cyc.long_ride_decoupling(*EMPTY)) == 0
        assert len(cyc.decoupling_by_type(*EMPTY)) == 0
