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

from anfra_client import AnfraClient, Condition, Filter, between, is_in

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


def _sport_filter(sports: tuple[str, ...]) -> list[Filter | Condition]:
    return [is_in("activities.sport_group", list(sports))] if sports else []


def _surface_filter(surfaces: tuple[str, ...]) -> list[Filter | Condition]:
    return [is_in("activities.run_surface", list(surfaces))] if surfaces else []


# --------------------------------------------------------------------------
# KPI strip
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def kpi_fitness() -> pd.DataFrame:
    """Latest-week CTL / ATL / TSB from the intervals.icu weekly summary."""
    res = get_client().aql(
        "metric latest_ctl = weekly_summary.ctl\n"
        "  | where(weekly_summary.week_start == max(weekly_summary.week_start));\n"
        "metric latest_atl = weekly_summary.atl\n"
        "  | where(weekly_summary.week_start == max(weekly_summary.week_start));\n"
        "metric latest_tsb = weekly_summary.tsb\n"
        "  | where(weekly_summary.week_start == max(weekly_summary.week_start));\n"
        "explore {\n"
        "  measures { ctl: latest_ctl, atl: latest_atl, tsb: latest_tsb }\n"
        "}"
    )
    return _frame(res)


@st.cache_data(ttl=300)
def kpi_week_distance(sports: tuple[str, ...], surfaces: tuple[str, ...]) -> pd.DataFrame:
    """This week's run km vs the trailing 4-week weekly average."""
    res = get_client().aql(
        "metric this_week_run_km = run_distance_km\n"
        "  | where(activities.week_start == max(activities.week_start));\n"
        "metric avg_4wk_run_km =\n"
        "  unique(activities.week_start) | select(v: run_distance_km) | avg(v);\n"
        "explore {\n"
        "  measures { this_week: this_week_run_km, avg_4wk: avg_4wk_run_km }\n"
        "  filters { activities.week_start matches @(last 4 weeks) }\n"
        "}",
        filters=_sport_filter(sports) + _surface_filter(surfaces),
        timezone=TIMEZONE,
    )
    df = _frame(res)
    return df.rename(columns={"this_week": "this_week_km", "avg_4wk": "avg_4wk_km"})


@st.cache_data(ttl=300)
def kpi_90d(sports: tuple[str, ...]) -> pd.DataFrame:
    """Total distance across all sports over the last 90 days (wall clock)."""
    res = get_client().aql(
        "explore {\n"
        "  measures { km: total_distance_km }\n"
        "  filters { activities.date matches @(last 90 days) }\n"
        "}",
        filters=_sport_filter(sports),
    )
    return _frame(res)


@st.cache_data(ttl=300)
def kpi_decoupling() -> pd.DataFrame:
    """Average HR decoupling and long-run count over the last 90 days."""
    res = get_client().aql(
        "explore {\n"
        "  measures {\n"
        "    avg_decoupling_pct: decoupling_calc.avg_decoupling,\n"
        "    long_runs: decoupling_calc.long_run_count\n"
        "  }\n"
        "  filters { decoupling_calc.activity_start matches @(last 90 days) }\n"
        "}",
        timezone=TIMEZONE,
    )
    return _frame(res).rename(columns={"avg_decoupling_pct": "avg_decoupling"})


# --------------------------------------------------------------------------
# Fitness & volume
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def fitness_trend(date_from: str, date_to: str) -> pd.DataFrame:
    res = get_client().aql(
        "explore {\n"
        "  dimensions {\n"
        "    week_start: weekly_summary.week_start\n"
        "  }\n"
        "  measures {\n"
        "    ctl: weekly_summary.ctl, atl: weekly_summary.atl, tsb: weekly_summary.tsb\n"
        "  }\n"
        "  sorts {\n"
        "    week_start asc\n"
        "  }\n"
        "}",
        filters=[between("weekly_summary.week_start", date_from, date_to)],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def sport_mix(date_from: str, date_to: str) -> pd.DataFrame:
    """Hours by sport (cross-filter SOURCE — deliberately ignores sport filters)."""
    res = get_client().aql(
        "explore {\n"
        "  dimensions {\n"
        "    sport_group: activities.sport_group\n"
        "  }\n"
        "  measures {\n"
        "    hours: total_time_h\n"
        "  }\n"
        "  sorts {\n"
        "    hours desc\n"
        "  }\n"
        "}",
        filters=[between("activities.date", date_from, date_to)],
        timezone=TIMEZONE,
    )
    return _frame(res)
