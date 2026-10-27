"""Live AQL data layer for the example app.

Template from the anfra-streamlit-apps skill. ADAPT for your app:
- rename ``example_`` to ``<app>_``,
- point DATASET / DATA_SOURCE / TIMEZONE at your repo,
- swap the run_* metrics / activities dims for your model's fields.

Keep everything else: the bootstrap, the cached client, filter helpers, the
date-only cross-filter source, and pandas-free query functions.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# Import bootstrap: put the repo root (anfra_client/) on sys.path — Streamlit
# only puts the script's own folder there.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402  (must follow the sys.path bootstrap)
import streamlit as st  # noqa: E402

from anfra_client import AnfraClient, between, is_in  # noqa: E402

DATASET = "running_analytics"
DATA_SOURCE = "running"
TIMEZONE = "Europe/Paris"

SURFACES = ("road", "trail", "indoor")
RUNS = "activities.sport_group in ['run']"


@st.cache_resource
def get_client() -> AnfraClient:
    return AnfraClient.from_env(dataset=DATASET)


def _frame(res) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    return res.frame()


def _filters(surfaces: tuple[str, ...]) -> list[str]:
    filters = [RUNS]
    if surfaces:
        filters.append(is_in("activities.run_surface", list(surfaces)))
    return filters


@st.cache_data(ttl=300)
def date_bounds() -> tuple[dt.date, dt.date]:
    """(earliest, latest) activity dates — the app's data clock (§presets)."""
    res = get_client().sql(
        "SELECT MIN(CAST(start_local AS DATE)) AS lo, MAX(CAST(start_local AS DATE)) AS hi"
        " FROM activities WHERE sport_group = 'run'",
        data_source=DATA_SOURCE,
    )
    row = _frame(res).iloc[0]
    return dt.date.fromisoformat(str(row["lo"])[:10]), dt.date.fromisoformat(str(row["hi"])[:10])


@st.cache_data(ttl=300)
def kpi_totals(date_from: str, date_to: str, surfaces: tuple[str, ...]) -> pd.DataFrame:
    """KPI strip inputs: total km + run count for the window."""
    res = get_client().query(
        measures={"km": "run_distance_km", "runs": "run_activities"},
        filters=[between("activities.date", date_from, date_to)] + _filters(surfaces),
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def weekly_distance(date_from: str, date_to: str, surfaces: tuple[str, ...]) -> pd.DataFrame:
    """Weekly km line — honors the surface filter (and the donut focus)."""
    res = get_client().query(
        dimensions=["activities.week_start"],
        measures={"km": "run_distance_km"},
        filters=[between("activities.date", date_from, date_to)] + _filters(surfaces),
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def mix_by_surface(date_from: str, date_to: str) -> pd.DataFrame:
    """Hours by surface — the cross-filter SOURCE: date-only by design so it
    stays stable while its own selection filters the other components."""
    res = get_client().query(
        dimensions=["activities.run_surface"],
        measures={"hours": "run_time_h"},
        filters=[between("activities.date", date_from, date_to), RUNS],
        order_by=["hours desc"],
        timezone=TIMEZONE,
    )
    return _frame(res)
