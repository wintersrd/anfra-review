"""AQL-backed data layer for the Streamlit app — consumer #1 of anfra_client.

Same function signatures and output columns as ``queries.py`` (the SQL
module, kept as the test oracle), but every query is expressed as AQL against
the anfra semantic layer and executed by ``anfra serve`` via the MCP client.
No SQL, no direct DuckDB access, no reader snapshot needed.

Metric math (pace, weighted stride, efficiency, ...) lives in the AML
datasets — this module only references metric names, which is the point of
the split: one definition, N consumers.

Migration status: KPI tier + fitness trend + sport mix are ported (verified
equivalent to the SQL layer by tests/integration/test_queries_aql_equiv.py).
The remaining chart queries follow the same three-line pattern — see
docs/anfra-client-guide.md.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from anfra_client import AnfraClient, Filter, between, is_in

DATASET = "running_analytics"
# Date truncation (weekly buckets, "last N" windows) must use the athlete's local
# timezone to match the SQL layer's date_trunc on local dates.
TIMEZONE = "Europe/Paris"


@st.cache_resource
def get_client() -> AnfraClient:
    """Shared MCP client (the server owns the DuckDB lock — always go through it)."""
    return AnfraClient.from_env(dataset=DATASET)


def _frame(res) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    return res.frame()


def _sport_filter(sports: tuple[str, ...]) -> list[Filter]:
    return [is_in("activities.sport_group", list(sports))] if sports else []


def _surface_filter(surfaces: tuple[str, ...]) -> list[Filter]:
    return [is_in("activities.run_surface", list(surfaces))] if surfaces else []


# --------------------------------------------------------------------------
# KPI strip
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def kpi_fitness() -> pd.DataFrame:
    """Latest-week CTL / ATL / TSB from the intervals.icu weekly summary."""
    res = get_client().query(
        custom_metrics={
            "latest_ctl": "weekly_summary.ctl"
            " | where(weekly_summary.week_start == max(weekly_summary.week_start))",
            "latest_atl": "weekly_summary.atl"
            " | where(weekly_summary.week_start == max(weekly_summary.week_start))",
            "latest_tsb": "weekly_summary.tsb"
            " | where(weekly_summary.week_start == max(weekly_summary.week_start))",
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
        measures=[("this_week", "this_week_run_km"), ("avg_4wk", "avg_4wk_run_km")],
        filters=["activities.week_start matches @(last 4 weeks)"]
        + _sport_filter(sports)
        + _surface_filter(surfaces),
        timezone=TIMEZONE,
    )
    df = _frame(res)
    return df.rename(columns={"this_week": "this_week_km", "avg_4wk": "avg_4wk_km"})


@st.cache_data(ttl=300)
def kpi_90d(sports: tuple[str, ...]) -> pd.DataFrame:
    """Total distance across all sports over the last 90 days (wall clock)."""
    res = get_client().query(
        measures={"km": "total_distance_km"},
        filters=["activities.date matches @(last 90 days)"] + _sport_filter(sports),
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
# Fitness & volume
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
