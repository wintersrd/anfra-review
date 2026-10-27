"""SQL validation oracle for the example app.

Reads the reader snapshot read-only, env-overridable via $EXAMPLE_DB so
AppTest can point the app at a fixture DB. Imported ONLY by tests — the app
never imports this module (that is the point: two independent roads to the
same numbers). ADAPT names/paths with your app.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import duckdb  # noqa: E402  (must follow the sys.path bootstrap)
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

READER_DB = Path(os.environ.get("EXAMPLE_DB") or (_REPO_ROOT / "data" / "running_reader.duckdb"))

SURFACES = ("road", "trail", "indoor")  # pinned equal to the live layer by unit test
RUNS = "sport_group = 'run'"


@st.cache_resource
def get_conn() -> duckdb.DuckDBPyConnection:
    if not READER_DB.exists():
        raise FileNotFoundError(
            f"{READER_DB} not found. Run: python3 scripts/sync_intervals_icu.py --build-only"
        )
    return duckdb.connect(str(READER_DB), read_only=True)


def _df(sql: str, params: list | None = None) -> pd.DataFrame:
    return get_conn().execute(sql, params or []).fetchdf()


def _surface_clause(surfaces: tuple[str, ...]) -> str:
    if not surfaces:
        return "1=1"
    return "run_surface IN ({})".format(", ".join(f"'{s}'" for s in surfaces if s in SURFACES))


def date_bounds() -> tuple[dt.date, dt.date]:
    row = _df(
        "SELECT MIN(CAST(start_local AS DATE)) AS lo, MAX(CAST(start_local AS DATE)) AS hi"
        f" FROM activities WHERE {RUNS}"
    ).iloc[0]
    return dt.date.fromisoformat(str(row["lo"])[:10]), dt.date.fromisoformat(str(row["hi"])[:10])


def kpi_totals(date_from: str, date_to: str, surfaces: tuple[str, ...]) -> pd.DataFrame:
    return _df(
        f"""
        SELECT SUM(distance_m) / 1000.0 AS km, COUNT(*) AS runs
        FROM activities
        WHERE {RUNS} AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {_surface_clause(surfaces)}
        """,
        [date_from, date_to],
    )


def weekly_distance(date_from: str, date_to: str, surfaces: tuple[str, ...]) -> pd.DataFrame:
    return _df(
        f"""
        SELECT date_trunc('week', start_local)::date AS week_start,
               SUM(distance_m) / 1000.0 AS km
        FROM activities
        WHERE {RUNS} AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {_surface_clause(surfaces)}
        GROUP BY 1 ORDER BY 1
        """,
        [date_from, date_to],
    )


def mix_by_surface(date_from: str, date_to: str) -> pd.DataFrame:
    return _df(
        f"""
        SELECT run_surface, SUM(moving_time_s) / 3600.0 AS hours
        FROM activities
        WHERE {RUNS} AND CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1 ORDER BY hours DESC
        """,
        [date_from, date_to],
    )
