"""AQL-backed data layer for the Streamlit app — consumer #1 of anfra_client.

Same function signatures and output columns as ``queries.py`` (the SQL
module, kept as the test oracle), but every query is expressed as AQL against
the anfra semantic layer and executed by ``anfra serve`` via the MCP client.
No direct DuckDB access, no reader snapshot needed — the server owns the lock.

Metric math (pace, weighted stride, efficiency, hilliness, ...) lives in the
AML datasets — this module only references metric names, which is the point
of the split: one definition, N consumers. Row-level guards that the SQL
oracle applies in WHERE clauses (``distance_m > 0`` etc.) are mirrored here
as string conditions so both layers stay numerically equivalent.

Every function is verified against the SQL oracle by
tests/integration/test_queries_aql_equiv.py.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from anfra_client import AnfraClient, Filter, between, is_in

DATASET = "running_analytics"
DATA_SOURCE = "running"
# Date truncation (weekly buckets, "last N" windows) must use the athlete's local
# timezone to match the SQL layer's date_trunc on local dates.
TIMEZONE = "Europe/Paris"

PACE_BUCKETS = ["<4:00", "4\u20135", "5\u20136", "6\u20137", "7+", "unknown"]

# The SQL oracle hardcodes `sport_group = 'run'` on every runs-only chart. The
# optional sports cross-filter is ANDed on top (picking 'ride' empties the
# chart — same as the anfra dashboard).
RUN_ONLY = "activities.sport_group in ['run']"


@st.cache_resource
def get_client() -> AnfraClient:
    """Shared MCP client (the server owns the DuckDB lock — always go through it)."""
    return AnfraClient.from_env(dataset=DATASET)


def _frame(res) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    return res.frame()


def _sport_filter(sports: tuple[str, ...]) -> list[Filter | str]:
    return [is_in("activities.sport_group", list(sports))] if sports else []


def _surface_filter(surfaces: tuple[str, ...]) -> list[Filter | str]:
    return [is_in("activities.run_surface", list(surfaces))] if surfaces else []


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def date_bounds() -> tuple[dt.date, dt.date]:
    """(earliest, latest) activity dates, for the sidebar date window."""
    res = get_client().sql(
        "SELECT MIN(CAST(start_local AS DATE)) AS lo,"
        " MAX(CAST(start_local AS DATE)) AS hi FROM activities",
        data_source=DATA_SOURCE,
    )
    row = _frame(res).iloc[0]
    return dt.date.fromisoformat(str(row["lo"])), dt.date.fromisoformat(str(row["hi"]))


# --------------------------------------------------------------------------
# KPI strip
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def kpi_fitness() -> pd.DataFrame:
    """Latest-week CTL / ATL / TSB from the intervals.icu weekly summary."""
    res = get_client().query(
        custom_metrics={
            name: f"weekly_summary.{col}"
            " | where(weekly_summary.week_start == max(weekly_summary.week_start))"
            for name, col in [("latest_ctl", "ctl"), ("latest_atl", "atl"), ("latest_tsb", "tsb")]
        },
        measures=[("ctl", "latest_ctl"), ("atl", "latest_atl"), ("tsb", "latest_tsb")],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def kpi_week_distance(sports: tuple[str, ...], surfaces: tuple[str, ...]) -> pd.DataFrame:
    """This week's run km vs the trailing 4-week weekly average."""
    res = get_client().query(
        custom_metrics={
            "this_week_run_km": "run_distance_km"
            " | where(activities.week_start == max(activities.week_start))",
            "avg_4wk_run_km": "unique(activities.week_start) | select(v: run_distance_km) | avg(v)",
        },
        measures=[("this_week_km", "this_week_run_km"), ("avg_4wk_km", "avg_4wk_run_km")],
        filters=["activities.week_start matches @(last 4 weeks)", RUN_ONLY]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def kpi_90d(sports: tuple[str, ...]) -> pd.DataFrame:
    """Total distance across all sports over the last 90 days (wall clock)."""
    res = get_client().query(
        measures={"km": "total_distance_km"},
        filters=[
            "activities.date matches @(last 90 days)",
            *_sport_filter(sports),
        ],
    )
    return _frame(res)


@st.cache_data(ttl=300)
def kpi_decoupling() -> pd.DataFrame:
    """Average HR decoupling and long-run count over the last 90 days."""
    res = get_client().query(
        measures={
            "avg_decoupling": "decoupling_calc.avg_decoupling",
            "long_runs": "decoupling_calc.long_run_count",
        },
        filters=["decoupling_calc.activity_start matches @(last 90 days)"],
        timezone=TIMEZONE,
    )
    return _frame(res)


# --------------------------------------------------------------------------
# Fitness & load (weekly_summary grain — full history, date window on week_start)
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def fitness_trend(date_from: str, date_to: str) -> pd.DataFrame:
    res = get_client().query(
        dimensions=["weekly_summary.week_start"],
        measures=["weekly_summary.ctl", "weekly_summary.atl", "weekly_summary.tsb"],
        filters=[between("weekly_summary.week_start", date_from, date_to)],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def load_ramp(date_from: str, date_to: str) -> pd.DataFrame:
    res = get_client().query(
        dimensions=["weekly_summary.week_start"],
        measures={
            "load": "weekly_summary.weekly_load",
            "ramp_rate": "weekly_summary.weekly_ramp_rate",
        },
        filters=[between("weekly_summary.week_start", date_from, date_to)],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


# --------------------------------------------------------------------------
# Volume (activities grain)
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def weekly_run_distance(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    res = get_client().query(
        dimensions=["activities.week_start"],
        measures={"run_km": "run_distance_km", "elev_gain_m": "run_elev_gain_m"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def daily_runs(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    res = get_client().query(
        dimensions=[("day", "activities.date")],
        measures={"km": "run_distance_km"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["day asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def sport_mix(date_from: str, date_to: str) -> pd.DataFrame:
    """Hours by sport (cross-filter SOURCE — deliberately ignores sport filters)."""
    res = get_client().query(
        dimensions=["activities.sport_group"],
        measures={"hours": "total_time_h"},
        filters=[between("activities.date", date_from, date_to)],
        order_by=["hours desc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def weekly_category(date_from: str, date_to: str) -> pd.DataFrame:
    res = get_client().query(
        dimensions=["weekly_by_category.week_start", "weekly_by_category.category"],
        measures={"hours": "weekly_by_category.cat_time_h"},
        filters=[between("weekly_by_category.week_start", date_from, date_to)],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


# --------------------------------------------------------------------------
# Speed & progression (runs only)
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def monthly_pace(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    res = get_client().query(
        dimensions=["activities.month"],
        measures={"pace_min_km": "run_pace_min_km", "moving_time_s": "activities.total_time_s"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + ["activities.distance_m > 0", "activities.moving_time_s > 0"]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def monthly_cadence(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    res = get_client().query(
        dimensions=["activities.month"],
        measures={"rpm": "run_avg_cadence"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + ["activities.avg_cadence > 40", "activities.moving_time_s > 0"]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def monthly_efficiency(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """Aerobic efficiency: m/s per heartbeat (Σ speed·t / Σ hr·t), runs only."""
    res = get_client().query(
        dimensions=["activities.month"],
        measures={"aerobic_efficiency": "run_aerobic_efficiency"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + [
            "activities.avg_speed_ms > 0",
            "activities.avg_hr > 0",
            "activities.moving_time_s > 0",
        ]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


# --------------------------------------------------------------------------
# Surface & stride
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def surface_pace_trend(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    res = get_client().query(
        dimensions=["activities.month", "activities.run_surface"],
        measures={"pace_min_km": "run_pace_min_km"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + ["activities.distance_m > 0", "activities.moving_time_s > 0"]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def stride_trend(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """Time-weighted average stride length per month and surface."""
    res = get_client().query(
        dimensions=["activities.month", "activities.run_surface"],
        measures={"stride_m": "run_stride_m"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + ["activities.stride_m is not null", "activities.stride_time_s > 0"]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def hilliness_trend(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    res = get_client().query(
        dimensions=["activities.month", "activities.run_surface"],
        measures={"elev_per_km": "run_elev_per_km"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + [
            "activities.distance_m > 0",
            "activities.elev_gain_m is not null",
        ]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def decoupling_by_surface(date_from: str, date_to: str) -> pd.DataFrame:
    res = get_client().query(
        custom_dimensions={
            "activities.surface_or_unknown": (
                "case(when: activities.run_surface is null, then: 'unknown',"
                " else: activities.run_surface)"
            )
        },
        dimensions=[("run_surface", "activities.surface_or_unknown")],
        measures={
            "avg_decoupling": "decoupling_calc.avg_decoupling",
            "long_runs": "decoupling_calc.long_run_count",
        },
        filters=[between("decoupling_calc.activity_start", date_from, date_to)],
        order_by=["avg_decoupling desc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def stride_vs_pace(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """One row per run with stride + pace; null-stride rows dropped (as in anfra)."""
    res = get_client().query(
        custom_dimensions={
            "activities.pace_from_speed": (
                "case(when: activities.distance_m > 0,"
                " then: activities.moving_time_s / 60.0"
                " / (activities.distance_m / 1000.0), else: null)"
            )
        },
        dimensions=[
            ("day", "activities.date"),
            "activities.name",
            "activities.run_surface",
            ("pace_min_km", "activities.pace_from_speed"),
            "activities.stride_m",
        ],
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + [
            "activities.stride_m is not null",
            "activities.distance_m > 0",
            "activities.moving_time_s > 0",
        ]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["day asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


# --------------------------------------------------------------------------
# Pace distribution
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def pace_blocks_weekly(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """Weekly running hours split into avg-pace buckets (min/km)."""
    res = get_client().query(
        custom_dimensions={
            "activities.pace_bucket_num": (
                "case("
                "when: activities.avg_speed_ms is null, then: -1,"
                "when: activities.avg_speed_ms > 4.16667, then: 1,"
                "when: activities.avg_speed_ms > 3.33333, then: 2,"
                "when: activities.avg_speed_ms > 2.77778, then: 3,"
                "when: activities.avg_speed_ms > 2.381, then: 4,"
                "else: 5)"
            ),
            "activities.pace_bucket": (
                "case("
                "when: activities.avg_speed_ms is null, then: 'unknown',"
                "when: activities.avg_speed_ms > 4.16667, then: '<4:00',"
                "when: activities.avg_speed_ms > 3.33333, then: '4\u20135',"
                "when: activities.avg_speed_ms > 2.77778, then: '5\u20136',"
                "when: activities.avg_speed_ms > 2.381, then: '6\u20137',"
                "else: '7+')"
            ),
        },
        dimensions=[
            ("week_start", "activities.week_start"),
            ("bucket", "activities.pace_bucket"),
            ("bucket_num", "activities.pace_bucket_num"),
        ],
        measures={"hours": "run_time_h"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + ["activities.moving_time_s > 0"]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["week_start asc", "bucket_num asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def decoupling_trend(date_from: str, date_to: str) -> pd.DataFrame:
    res = get_client().query(
        dimensions=[
            ("activity_start", "decoupling_calc.activity_start"),
            ("name", "decoupling_calc.name"),
        ],
        measures={"decoupling_pct": "decoupling_calc.avg_decoupling"},
        filters=[between("decoupling_calc.activity_start", date_from, date_to)],
        order_by=["activity_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def pace_by_temp(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """Average pace per 5\u00b0C bucket of the recorded run temperature."""
    res = get_client().query(
        custom_dimensions={"activities.temp_bucket_low": "floor(activities.avg_temp_c / 5) * 5"},
        dimensions=[("bucket_low", "activities.temp_bucket_low")],
        measures={"pace_min_km": "run_pace_min_km", "runs": "run_activities"},
        filters=[between("activities.date", date_from, date_to)]
        + [RUN_ONLY]
        + [
            "activities.avg_temp_c is not null",
            "activities.distance_m > 0",
            "activities.moving_time_s > 0",
        ]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        order_by=["bucket_low asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)
