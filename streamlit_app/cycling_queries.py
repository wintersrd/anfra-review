"""SQL oracle for the cycling app — raw DuckDB over the reader snapshot.

One function per app component, same signatures/shapes as the live AQL layer
(``cycling_queries_aql.py``). This module is imported ONLY by tests; the app
renders through the AQL layer. The equivalence suite
(tests/integration/test_cycling_equiv.py) pins oracle ≡ live on the default
window, an empty window and a narrowed filter.

Data-layer math mirrored between the layers (documented per §skill):
- %FTP zone / cadence / temperature bucketing as SQL CASE here, AQL custom
  dimensions there — labels and edges are the shared constants below.
- Ramp rate (§8.7) is a within-window diff (first visible week = gap).
- K2's 4-complete-week mean (§7-K2, D13): fetched at week grain, summed and
  divided by 4 — no-ride weeks count as zero.
Row-level guards (watts > 0, cadence > 40, distance ≥ 1000 m) mirror the
string conditions of the live layer so both filter identically.

Reads ``data/running_reader.duckdb`` (read-only; the anfra server owns the
write lock). Path overridable with ``$CYCLING_DB`` so AppTest can point the
app at a fixture database.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
READER_DB = REPO_ROOT / "data" / "running_reader.duckdb"

# --- shared constants (pinned equal with the live layer by unit tests) -----
RIDE_TYPES = ["road", "virtual", "mtb", "gravel"]  # canonical order (§6.3)
LONG_RIDE_MIN_S = 4500  # §4 long ride = ≥75 min moving
CADENCE_MIN_RPM = 40  # §8.4 coast-artifact guard
MIN_RIDE_M = 1000  # §8.6 ≥1 km rides for speed/hilliness
TEMP_BUCKET_STEP_C = 5  # §7-C15
TEMP_FLOOR_C = -5

# §8.2 zones, left-inclusive [lo, hi); labels use en-dashes.
FTP_ZONE_LABELS = ["Z1 <55", "Z2 55–75", "Z3 75–90", "Z4 90–105", "Z5 105–120", "Z6 120+"]
FTP_ZONE_EDGES = [55.0, 75.0, 90.0, 105.0, 120.0]
# Cadence buckets for C12 (spec §8.6 mis-cite; edges per WORKLOG D6).
CADENCE_BUCKETS = ["<70", "70–80", "80–90", "90–100", "100+"]
CADENCE_EDGES = [70.0, 80.0, 90.0, 100.0]

RIDES = "ride_type IS NOT NULL"
POWER = "weighted_avg_watts IS NOT NULL AND weighted_avg_watts > 0"
CADENCE = f"avg_cadence > {CADENCE_MIN_RPM}"


@st.cache_resource
def get_conn() -> duckdb.DuckDBPyConnection:
    path = os.environ.get("CYCLING_DB") or str(READER_DB)
    if not Path(path).exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python3 scripts/sync_intervals_icu.py --build-only"
        )
    return duckdb.connect(path, read_only=True)


def _df(sql: str, params: list | None = None) -> pd.DataFrame:
    return get_conn().execute(sql, params or []).fetchdf()


def _types_clause(types: tuple[str, ...]) -> str:
    if not types:
        return "1=1"
    return "ride_type IN ({})".format(", ".join(f"'{t}'" for t in types))


# ---------------------------------------------------------------------------
# Metadata + KPI strip
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def date_bounds() -> tuple[dt.date, dt.date]:
    """(earliest, latest) ride dates — the app's clock is the data's (§6.2)."""
    row = _df(
        f"SELECT MIN(CAST(start_local AS DATE)) AS lo, MAX(CAST(start_local AS DATE)) AS hi"
        f" FROM activities WHERE {RIDES}"
    ).iloc[0]
    return dt.date.fromisoformat(str(row["lo"])[:10]), dt.date.fromisoformat(str(row["hi"])[:10])


@st.cache_data(ttl=300)
def kpi_ftp() -> pd.DataFrame:
    """K1 — current FTP: ftp_ref of the most recent ride (§8.1). Empty = case 3."""
    return _df(
        f"SELECT ftp_ref AS ftp_w FROM activities WHERE {RIDES} ORDER BY start_local DESC LIMIT 1"
    )


@st.cache_data(ttl=300)
def kpi_ride_km_week(types: tuple[str, ...], today: dt.date | None = None) -> pd.DataFrame:
    """K2 — this ISO week's ride km vs mean of the 4 preceding complete weeks.

    Current week = Monday-start week containing wall-clock today (§4). A
    complete week's Monday ≤ current Monday − 7 d, so the four are M−28…M−7;
    weeks with no rides count as 0 km in the mean (D13).
    """
    today = today or dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    mondays = [monday - dt.timedelta(days=7 * i) for i in range(5)]
    rows = _df(
        f"SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start,"
        f" SUM(distance_m) / 1000.0 AS km"
        f" FROM activities WHERE {RIDES} AND {_types_clause(types)}"
        " AND date_trunc('week', CAST(start_local AS DATE)) IN (?, ?, ?, ?, ?)"
        " GROUP BY 1",
        mondays,
    )
    by_week = {pd.Timestamp(w).date(): (0.0 if pd.isna(km) else float(km)) for w, km in rows.values}
    this_week = by_week.get(monday, 0.0)
    avg_4wk = sum(by_week.get(m, 0.0) for m in mondays[1:]) / 4.0
    return pd.DataFrame({"this_week_km": [this_week], "avg_4wk_km": [avg_4wk]})


@st.cache_data(ttl=300)
def kpi_elev_90d(types: tuple[str, ...], today: dt.date | None = None) -> pd.DataFrame:
    """K3 — Σ elev gain + Σ km over rides in the last 90 days (wall clock)."""
    today = today or dt.date.today()
    frm = (today - dt.timedelta(days=89)).isoformat()
    to = today.isoformat()
    return _df(
        f"SELECT SUM(elev_gain_m) AS elev_gain_m, SUM(distance_m) / 1000.0 AS km"
        f" FROM activities WHERE {RIDES} AND {_types_clause(types)}"
        " AND CAST(start_local AS DATE) BETWEEN ? AND ?",
        [frm, to],
    )


@st.cache_data(ttl=300)
def kpi_if_90d(types: tuple[str, ...], today: dt.date | None = None) -> pd.DataFrame:
    """K4 — duration-weighted mean IF over rides with power, last 90 d (§8.3)."""
    today = today or dt.date.today()
    frm = (today - dt.timedelta(days=89)).isoformat()
    to = today.isoformat()
    return _df(
        f"SELECT SUM((weighted_avg_watts / ftp_ref) * moving_time_s)"
        f" / NULLIF(SUM(moving_time_s), 0) AS if_mean,"
        f" COUNT(*) AS rides_with_power"
        f" FROM activities WHERE {RIDES} AND {POWER} AND {_types_clause(types)}"
        " AND CAST(start_local AS DATE) BETWEEN ? AND ?",
        [frm, to],
    )


# ---------------------------------------------------------------------------
# C1 / C2 — weekly grain (athlete-level fitness, cycling load)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def fitness_trend(date_from: str, date_to: str) -> pd.DataFrame:
    """C1 — CTL/ATL/TSB weekly, earliest week → window end (D9: date_from ignored)."""
    return _df(
        "SELECT week_start, fitness AS ctl, fatigue AS atl, form AS tsb"
        " FROM weekly_summary WHERE week_start <= ? ORDER BY week_start",
        [date_to],
    )


@st.cache_data(ttl=300)
def weekly_load_ramp(date_from: str, date_to: str) -> pd.DataFrame:
    """C2 — weekly cycling load (weekly_by_category 'Ride') + ramp (§8.7 in-window diff)."""
    return _df(
        "SELECT week_start, training_load AS load,"
        " training_load - LAG(training_load) OVER (ORDER BY week_start) AS ramp"
        " FROM weekly_by_category WHERE category = 'Ride' AND week_start BETWEEN ? AND ?"
        " ORDER BY week_start",
        [date_from, date_to],
    )


# ---------------------------------------------------------------------------
# C3–C6 — volume & consistency (activity grain)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def weekly_ride_distance(date_from: str, date_to: str) -> pd.DataFrame:
    """C3 — weekly ride km + weekly elevation gain."""
    return _df(
        f"SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start,"
        f" SUM(distance_m) / 1000.0 AS ride_km, SUM(elev_gain_m) AS elev_gain_m"
        f" FROM activities WHERE {RIDES} AND CAST(start_local AS DATE) BETWEEN ? AND ?"
        " GROUP BY 1 ORDER BY 1",
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def ride_calendar(date_from: str, date_to: str) -> pd.DataFrame:
    """C4 — daily ride km (the app pivots to weekday × ISO-week grid)."""
    return _df(
        f"SELECT CAST(start_local AS DATE) AS day, SUM(distance_m) / 1000.0 AS km"
        f" FROM activities WHERE {RIDES} AND CAST(start_local AS DATE) BETWEEN ? AND ?"
        " GROUP BY 1 ORDER BY 1",
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def ride_mix(date_from: str, date_to: str) -> pd.DataFrame:
    """C5 — hours by ride type (cross-filter SOURCE; date-only by design)."""
    return _df(
        f"SELECT ride_type, SUM(moving_time_s) / 3600.0 AS hours"
        f" FROM activities WHERE {RIDES} AND CAST(start_local AS DATE) BETWEEN ? AND ?"
        " GROUP BY 1",
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def weekly_hours_by_type(date_from: str, date_to: str) -> pd.DataFrame:
    """C6 — weekly hours per ride type (weekly grain per §7-C6: date-only)."""
    return _df(
        f"SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start, ride_type,"
        f" SUM(moving_time_s) / 3600.0 AS hours"
        f" FROM activities WHERE {RIDES} AND CAST(start_local AS DATE) BETWEEN ? AND ?"
        " GROUP BY 1, 2 ORDER BY 1, 2",
        [date_from, date_to],
    )


# ---------------------------------------------------------------------------
# C7–C9 — power (rides with power only; §3.3 captions carry qualifying counts)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def rides_with_power(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """Caption counts for power components: (rides with power, all rides)."""
    return _df(
        f"SELECT COALESCE(SUM(CASE WHEN {POWER} THEN 1 ELSE 0 END), 0) AS with_power,"
        " COUNT(*) AS total"
        f" FROM activities WHERE {RIDES} AND {_types_clause(types)}"
        " AND CAST(start_local AS DATE) BETWEEN ? AND ?",
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def power_zones_weekly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C7 — weekly moving hours per %FTP zone (§8.2 left-inclusive buckets)."""
    return _df(
        f"""
        WITH z AS (
          SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start,
                 moving_time_s,
                 CASE
                   WHEN weighted_avg_watts / ftp_ref * 100 < 55 THEN '{FTP_ZONE_LABELS[0]}'
                   WHEN weighted_avg_watts / ftp_ref * 100 < 75 THEN '{FTP_ZONE_LABELS[1]}'
                   WHEN weighted_avg_watts / ftp_ref * 100 < 90 THEN '{FTP_ZONE_LABELS[2]}'
                   WHEN weighted_avg_watts / ftp_ref * 100 < 105 THEN '{FTP_ZONE_LABELS[3]}'
                   WHEN weighted_avg_watts / ftp_ref * 100 < 120 THEN '{FTP_ZONE_LABELS[4]}'
                   ELSE '{FTP_ZONE_LABELS[5]}'
                 END AS zone
          FROM activities
          WHERE {RIDES} AND {POWER} AND {_types_clause(types)}
            AND CAST(start_local AS DATE) BETWEEN ? AND ?
        )
        SELECT week_start, zone, SUM(moving_time_s) / 3600.0 AS hours
        FROM z GROUP BY 1, 2 ORDER BY 1, 2
        """,
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def intensity_trend(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C8 — monthly duration-weighted IF and mean %FTP (§8.2/§8.3)."""
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month,
               SUM((weighted_avg_watts / ftp_ref) * moving_time_s)
                 / NULLIF(SUM(moving_time_s), 0) AS if_mean,
               SUM((weighted_avg_watts / ftp_ref * 100.0) * moving_time_s)
                 / NULLIF(SUM(moving_time_s), 0) AS pct_ftp
        FROM activities
        WHERE {RIDES} AND {POWER} AND {_types_clause(types)}
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1 ORDER BY 1
        """,
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def power_weight_weekly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C9 — weekly mean weighted watts + W/kg (§8.5); W/kg null when no weight."""
    return _df(
        f"""
        SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start,
               SUM(weighted_avg_watts * moving_time_s)
                 / NULLIF(SUM(moving_time_s) FILTER (WHERE {POWER}), 0) AS watts,
               SUM((weighted_avg_watts / weight_ref_kg) * moving_time_s)
                 / NULLIF(
                     SUM(moving_time_s)
                       FILTER (WHERE {POWER} AND weight_ref_kg IS NOT NULL), 0) AS w_per_kg
        FROM activities
        WHERE {RIDES} AND {_types_clause(types)}
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1 ORDER BY 1
        """,
        [date_from, date_to],
    )


# ---------------------------------------------------------------------------
# C10–C15 — speed & cadence
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def speed_by_type_monthly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C10 — monthly true speed (§8.8) per ride type, ≥1 km rides, gaps kept."""
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month, ride_type,
               SUM(distance_m) / NULLIF(SUM(moving_time_s), 0) * 3.6 AS speed_kmh
        FROM activities
        WHERE {RIDES} AND distance_m >= {MIN_RIDE_M} AND {_types_clause(types)}
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def cadence_by_type_monthly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C11 — monthly duration-weighted cadence (§8.4 guard) per ride type."""
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month, ride_type,
               SUM(avg_cadence * moving_time_s) / NULLIF(SUM(moving_time_s), 0) AS rpm
        FROM activities
        WHERE {RIDES} AND {CADENCE} AND {_types_clause(types)}
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def cadence_buckets_weekly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C12 — weekly hours in cadence buckets (edges per D6), cadence rides only."""
    return _df(
        f"""
        WITH c AS (
          SELECT date_trunc('week', CAST(start_local AS DATE)) AS week_start,
                 moving_time_s,
                 CASE
                   WHEN avg_cadence < 70 THEN '{CADENCE_BUCKETS[0]}'
                   WHEN avg_cadence < 80 THEN '{CADENCE_BUCKETS[1]}'
                   WHEN avg_cadence < 90 THEN '{CADENCE_BUCKETS[2]}'
                   WHEN avg_cadence < 100 THEN '{CADENCE_BUCKETS[3]}'
                   ELSE '{CADENCE_BUCKETS[4]}'
                 END AS bucket
          FROM activities
          WHERE {RIDES} AND {CADENCE} AND {_types_clause(types)}
            AND CAST(start_local AS DATE) BETWEEN ? AND ?
        )
        SELECT week_start, bucket, SUM(moving_time_s) / 3600.0 AS hours
        FROM c GROUP BY 1, 2 ORDER BY 1, 2
        """,
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def cadence_vs_speed(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C13 — per-ride scatter source: speed vs cadence (§8.4 guard, D7)."""
    return _df(
        f"""
        SELECT CAST(start_local AS DATE) AS day, name, ride_type,
               avg_speed_ms * 3.6 AS speed_kmh, avg_cadence AS cadence
        FROM activities
        WHERE {RIDES} AND {CADENCE} AND avg_speed_ms IS NOT NULL
          AND {_types_clause(types)}
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        ORDER BY day
        """,
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def hilliness_by_type_monthly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C14 — monthly Σelev/Σdist×1000 (§8.6) per ride type, ≥1 km rides."""
    return _df(
        f"""
        SELECT date_trunc('month', CAST(start_local AS DATE)) AS month, ride_type,
               SUM(elev_gain_m) / NULLIF(SUM(distance_m), 0) * 1000.0 AS elev_per_km
        FROM activities
        WHERE {RIDES} AND distance_m >= {MIN_RIDE_M} AND elev_gain_m IS NOT NULL
          AND {_types_clause(types)}
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def speed_by_temp(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C15 — mean speed (§8.8) per 5 °C bucket, floored at −5 °C; rides with temp."""
    return _df(
        f"""
        SELECT GREATEST(FLOOR(avg_temp_c / {TEMP_BUCKET_STEP_C}) * {TEMP_BUCKET_STEP_C},
               {TEMP_FLOOR_C}) AS bucket_low,
               SUM(distance_m) / NULLIF(SUM(moving_time_s), 0) * 3.6 AS speed_kmh,
               COUNT(*) AS rides
        FROM activities
        WHERE {RIDES} AND avg_temp_c IS NOT NULL AND {_types_clause(types)}
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1 ORDER BY 1
        """,
        [date_from, date_to],
    )


# ---------------------------------------------------------------------------
# C16–C17 — endurance (long rides; intervals.icu-provided decoupling §8.9)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def long_ride_decoupling(date_from: str, date_to: str) -> pd.DataFrame:
    """C16 — decoupling % per long ride (§4); date-only filter by design."""
    return _df(
        f"""
        SELECT CAST(start_local AS DATE) AS day, name, decoupling AS decoupling_pct
        FROM activities
        WHERE {RIDES} AND moving_time_s >= {LONG_RIDE_MIN_S}
          AND decoupling IS NOT NULL
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        ORDER BY day
        """,
        [date_from, date_to],
    )


@st.cache_data(ttl=300)
def decoupling_by_type(date_from: str, date_to: str) -> pd.DataFrame:
    """C17 — mean decoupling per ride type over long rides + qualifying counts."""
    return _df(
        f"""
        SELECT ride_type, AVG(decoupling) AS avg_decoupling, COUNT(*) AS long_rides
        FROM activities
        WHERE {RIDES} AND moving_time_s >= {LONG_RIDE_MIN_S}
          AND decoupling IS NOT NULL
          AND CAST(start_local AS DATE) BETWEEN ? AND ?
        GROUP BY 1 ORDER BY 2 DESC
        """,
        [date_from, date_to],
    )
