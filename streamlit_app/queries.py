"""Data access layer for the Streamlit running-analytics app.

Reads the reader snapshot ``data/running_reader.duckdb`` (written by
``scripts/sync_intervals_icu.py`` after every build). All query functions are
cached: the connection per session, result frames by arguments (TTL 5 min).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
READER_DB = REPO_ROOT / "data" / "running_reader.duckdb"

RUNS_ONLY = "sport_group = 'run'"


@st.cache_resource
def get_conn() -> duckdb.DuckDBPyConnection:
    if not READER_DB.exists():
        raise FileNotFoundError(
            f"{READER_DB} not found. Run: python3 scripts/sync_intervals_icu.py --build-only"
        )
    return duckdb.connect(str(READER_DB), read_only=True)


@st.cache_data(ttl=300)
def date_bounds() -> tuple[dt.date, dt.date]:
    """(earliest, latest) activity dates, for the sidebar date window."""
    row = _df(
        "SELECT MIN(CAST(start_local AS DATE)) AS lo, MAX(CAST(start_local AS DATE)) AS hi FROM activities"
    ).iloc[0]
    return row["lo"], row["hi"]


def _df(sql: str, params: dict | None = None) -> pd.DataFrame:
    conn = get_conn()
    return conn.execute(sql, params or {}).fetchdf()


# --------------------------------------------------------------------------
# Shared filter fragments. The anfra app maps the date window grain-natively
# (activities.date, weekly_summary.week_start, decoupling_calc.activity_start);
# we do the same here.
# --------------------------------------------------------------------------


def _sport_clause(sports: tuple[str, ...], col: str = "sport_group") -> str:
    if not sports:
        return "1=1"
    joined = ", ".join(f"'{s}'" for s in sports)
    return f"{col} IN ({joined})"


def _surface_clause(surfaces: tuple[str, ...], col: str = "run_surface") -> str:
    if not surfaces:
        return "1=1"
    joined = ", ".join(f"'{s}'" for s in surfaces)
    return f"{col} IN ({joined})"


# --------------------------------------------------------------------------
# KPI strip
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def kpi_fitness() -> pd.DataFrame:
    """Latest-week CTL / ATL / TSB from the intervals.icu weekly summary."""
    return _df(
        """
        SELECT fitness AS ctl, fatigue AS atl, form AS tsb
        FROM weekly_summary
        WHERE week_start = (SELECT MAX(week_start) FROM weekly_summary)
        """
    )


@st.cache_data(ttl=300)
def kpi_week_distance(
    sports: tuple[str, ...], surfaces: tuple[str, ...]
) -> pd.DataFrame:
    """This week's run km vs the trailing 4-week weekly average."""
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        WITH weekly AS (
            SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start,
                   SUM(distance_m) / 1000.0 AS km
            FROM activities
            WHERE sport_group = 'run' AND distance_m IS NOT NULL
              AND {surf} AND {sport}
            GROUP BY 1
        ),
        recent AS (
            SELECT km, ROW_NUMBER() OVER (ORDER BY week_start DESC) AS rn FROM (
                SELECT week_start, km FROM weekly ORDER BY week_start DESC LIMIT 4
            )
        )
        SELECT
            MAX(CASE WHEN rn = 1 THEN km END) AS this_week_km,
            AVG(km) AS avg_4wk_km
        FROM recent
        """
    )


@st.cache_data(ttl=300)
def kpi_90d(sports: tuple[str, ...]) -> pd.DataFrame:
    """Total distance across all sports over the last 90 days."""
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT COALESCE(SUM(distance_m) / 1000.0, 0) AS km
        FROM activities
        WHERE CAST(start_local AS DATE) >= (SELECT MAX(CAST(start_local AS DATE)) FROM activities) - 89
          AND distance_m IS NOT NULL
          AND {sport}
        """
    )


@st.cache_data(ttl=300)
def kpi_decoupling() -> pd.DataFrame:
    """Average HR decoupling and long-run count over the last 90 days."""
    return _df(
        """
        SELECT AVG(decoupling_pct) AS avg_decoupling, COUNT(*) AS long_runs
        FROM decoupling_calc
        WHERE CAST(activity_start AS DATE) >= CURRENT_DATE - 90
        """
    )


# --------------------------------------------------------------------------
# Fitness & load (weekly_summary grain — full history, date window on week_start)
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def fitness_trend(date_from: str, date_to: str) -> pd.DataFrame:
    return _df(
        """
        SELECT week_start, fitness AS ctl, fatigue AS atl, form AS tsb
        FROM weekly_summary
        WHERE week_start BETWEEN ? AND ?
        ORDER BY week_start
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def load_ramp(date_from: str, date_to: str) -> pd.DataFrame:
    return _df(
        """
        SELECT week_start, training_load AS load, ramp_rate
        FROM weekly_summary
        WHERE week_start BETWEEN ? AND ?
        ORDER BY week_start
        """,
        {"1": date_from, "2": date_to},
    )


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
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start,
               SUM(distance_m) / 1000.0 AS run_km,
               SUM(elev_gain_m) AS elev_gain_m
        FROM activities
        WHERE sport_group = 'run' AND distance_m IS NOT NULL
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def daily_runs(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT CAST(start_local AS DATE) AS day, SUM(distance_m) / 1000.0 AS km
        FROM activities
        WHERE sport_group = 'run' AND distance_m IS NOT NULL
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def sport_mix(date_from: str, date_to: str) -> pd.DataFrame:
    return _df(
        """
        SELECT sport_group, SUM(moving_time_s) / 3600.0 AS hours
        FROM activities
        WHERE CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1 ORDER BY 2 DESC
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def weekly_category(date_from: str, date_to: str) -> pd.DataFrame:
    return _df(
        """
        SELECT week_start, category, SUM(time_s) / 3600.0 AS hours
        FROM weekly_by_category
        WHERE week_start BETWEEN ? AND ?
        GROUP BY 1, 2
        ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


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
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month,
               SUM(moving_time_s) / 60.0 / NULLIF(SUM(distance_m) / 1000.0, 0) AS pace_min_km,
               SUM(moving_time_s) AS moving_time_s
        FROM activities
        WHERE sport_group = 'run' AND distance_m > 0 AND moving_time_s > 0
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def monthly_cadence(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month,
               SUM(avg_cadence * moving_time_s) / NULLIF(SUM(moving_time_s), 0) AS rpm
        FROM activities
        WHERE sport_group = 'run' AND avg_cadence > 40 AND moving_time_s > 0
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def monthly_efficiency(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """Aerobic efficiency: m/s per heartbeat (Σ speed·t / Σ hr·t), runs only."""
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month,
               SUM(avg_speed_ms * moving_time_s) / NULLIF(SUM(avg_hr * moving_time_s), 0)
                   AS aerobic_efficiency
        FROM activities
        WHERE sport_group = 'run' AND avg_speed_ms > 0 AND avg_hr > 0 AND moving_time_s > 0
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


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
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month,
               run_surface,
               SUM(moving_time_s) / 60.0 / NULLIF(SUM(distance_m) / 1000.0, 0) AS pace_min_km
        FROM activities
        WHERE sport_group = 'run' AND distance_m > 0 AND moving_time_s > 0
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1, 2 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def stride_trend(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """Time-weighted average stride length per month and surface."""
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month,
               run_surface,
               SUM(stride_m * stride_time_s) / NULLIF(SUM(stride_time_s), 0) AS stride_m
        FROM activities
        WHERE sport_group = 'run' AND stride_m IS NOT NULL AND stride_time_s > 0
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1, 2 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def hilliness_trend(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month,
               run_surface,
               SUM(elev_gain_m) / NULLIF(SUM(distance_m), 0) * 1000 AS elev_per_km
        FROM activities
        WHERE sport_group = 'run' AND distance_m > 0 AND elev_gain_m IS NOT NULL
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1, 2 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def decoupling_by_surface(date_from: str, date_to: str) -> pd.DataFrame:
    return _df(
        """
        SELECT
            CASE
                WHEN a.run_surface IS NOT NULL THEN a.run_surface
                ELSE 'unknown'
            END AS run_surface,
            AVG(d.decoupling_pct) AS avg_decoupling,
            COUNT(*) AS long_runs
        FROM decoupling_calc d
        JOIN activities a ON a.id = d.activity_id
        WHERE CAST(d.activity_start AS DATE) BETWEEN ? AND ?
        GROUP BY 1 ORDER BY 2 DESC
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def stride_vs_pace(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """One row per run with stride + pace; null-stride rows dropped (as in anfra)."""
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT CAST(start_local AS DATE) AS day,
               name,
               run_surface,
               moving_time_s / 60.0 / (distance_m / 1000.0) AS pace_min_km,
               stride_m
        FROM activities
        WHERE sport_group = 'run' AND stride_m IS NOT NULL AND distance_m > 0
          AND moving_time_s > 0
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        ORDER BY day
        """,
        {"1": date_from, "2": date_to},
    )


# --------------------------------------------------------------------------
# Pace distribution
# --------------------------------------------------------------------------

PACE_BUCKETS = ["<4:00", "4\u20135", "5\u20136", "6\u20137", "7+", "unknown"]


@st.cache_data(ttl=300)
def pace_blocks_weekly(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """Weekly running hours split into avg-pace buckets (min/km)."""
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        WITH binned AS (
            SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start,
                   SUM(moving_time_s) / 3600.0 AS hours,
                   CASE
                       WHEN avg_speed_ms > 4.16667 THEN '<4:00'
                       WHEN avg_speed_ms > 3.33333 THEN '4\u20135'
                       WHEN avg_speed_ms > 2.77778 THEN '5\u20136'
                       WHEN avg_speed_ms > 2.381 THEN '6\u20137'
                       WHEN avg_speed_ms IS NOT NULL THEN '7+'
                       ELSE 'unknown'
                   END AS bucket,
                   CASE
                       WHEN avg_speed_ms > 4.16667 THEN 1
                       WHEN avg_speed_ms > 3.33333 THEN 2
                       WHEN avg_speed_ms > 2.77778 THEN 3
                       WHEN avg_speed_ms > 2.381 THEN 4
                       WHEN avg_speed_ms IS NOT NULL THEN 5
                       ELSE -1
                   END AS bucket_num
            FROM activities
            WHERE sport_group = 'run' AND moving_time_s > 0
              AND CAST(start_local AS DATE) BETWEEN ? AND ?
              AND {surf} AND {sport}
            GROUP BY 1, 3, 4
        )
        SELECT week_start, bucket, bucket_num, SUM(hours) AS hours
        FROM binned
        GROUP BY 1, 2, 3
        ORDER BY 1, bucket_num        """,
        {"1": date_from, "2": date_to},
    )


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------


@st.cache_data(ttl=300)
def decoupling_trend(date_from: str, date_to: str) -> pd.DataFrame:
    return _df(
        """
        SELECT activity_start, name, decoupling_pct
        FROM decoupling_calc
        WHERE CAST(activity_start AS DATE) BETWEEN ? AND ?
        ORDER BY activity_start
        """,
        {"1": date_from, "2": date_to},
    )


@st.cache_data(ttl=300)
def pace_by_temp(
    date_from: str,
    date_to: str,
    sports: tuple[str, ...],
    surfaces: tuple[str, ...],
) -> pd.DataFrame:
    """Average pace per 5\u00b0C bucket of the recorded run temperature."""
    surf = _surface_clause(surfaces)
    sport = _sport_clause(sports)
    return _df(
        f"""
        SELECT FLOOR(avg_temp_c / 5) * 5 AS bucket_low,
               SUM(moving_time_s) / 60.0 / NULLIF(SUM(distance_m) / 1000.0, 0) AS pace_min_km,
               COUNT(*) AS runs
        FROM activities
        WHERE sport_group = 'run' AND avg_temp_c IS NOT NULL
          AND distance_m > 0 AND moving_time_s > 0
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
          AND {surf} AND {sport}
        GROUP BY 1 ORDER BY 1
        """,
        {"1": date_from, "2": date_to},
    )
