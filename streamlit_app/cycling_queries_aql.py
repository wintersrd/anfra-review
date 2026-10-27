"""AQL-backed live data layer for the cycling app — consumer of anfra_client.

Same function signatures and output columns as ``cycling_queries.py`` (the SQL
oracle); every query is AQL against the anfra semantic layer executed by
``anfra serve`` over MCP. No direct DuckDB access — the server owns the lock.

Definitions live in the AML (datasets/running_analytics.dataset.aml); this
module only references fields/metrics. Row-level guards mirror the oracle's
WHERE clauses as string conditions so both layers filter identically:
power ``weighted_avg_watts > 0`` (NULL fails the comparison in both engines),
cadence ``avg_cadence > 40`` (§8.4), ``distance_m >= 1000`` (§8.6).

Mechanisms mirrored from the oracle and pinned by the equivalence suite
(tests/integration/test_cycling_equiv.py):
- ramp rate (§8.7): within-window diff (``load.diff()``) — first week gap;
- K2's 4-complete-week mean (D13): week-grain fetch ÷ 4, no-ride weeks = 0;
- C9: two queries (power weeks, power+weight weeks) outer-merged on week —
  weeks lacking weight gap the W/kg series only (§7-C9).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# Location-independent import bootstrap (spec Appendix B): the repo root must
# be on sys.path before anfra_client imports — Streamlit only puts the
# script's folder there.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402  (must follow sys.path bootstrap above)
import streamlit as st  # noqa: E402

from anfra_client import AnfraClient, Filter, between, is_in  # noqa: E402

DATASET = "running_analytics"
DATA_SOURCE = "running"
# Week/month truncation must match the SQL layer's date_trunc on local dates.
TIMEZONE = "Europe/Paris"

# --- shared constants (pinned equal with the oracle by unit tests) ---------
RIDE_TYPES = ["road", "virtual", "mtb", "gravel"]
LONG_RIDE_MIN_S = 4500
CADENCE_MIN_RPM = 40
MIN_RIDE_M = 1000
TEMP_BUCKET_STEP_C = 5
TEMP_FLOOR_C = -5

FTP_ZONE_LABELS = ["Z1 <55", "Z2 55–75", "Z3 75–90", "Z4 90–105", "Z5 105–120", "Z6 120+"]
FTP_ZONE_EDGES = [55.0, 75.0, 90.0, 105.0, 120.0]
CADENCE_BUCKETS = ["<70", "70–80", "80–90", "90–100", "100+"]
CADENCE_EDGES = [70.0, 80.0, 90.0, 100.0]

RIDES = "activities.ride_type is not null"
POWER = "activities.weighted_avg_watts > 0"
CADENCE = f"activities.avg_cadence > {CADENCE_MIN_RPM}"

_ZONE_CASE = (
    "case("
    "when: (activities.weighted_avg_watts / activities.ftp_ref * 100.0) < 55,"
    f" then: '{FTP_ZONE_LABELS[0]}',"
    "when: (activities.weighted_avg_watts / activities.ftp_ref * 100.0) < 75,"
    f" then: '{FTP_ZONE_LABELS[1]}',"
    "when: (activities.weighted_avg_watts / activities.ftp_ref * 100.0) < 90,"
    f" then: '{FTP_ZONE_LABELS[2]}',"
    "when: (activities.weighted_avg_watts / activities.ftp_ref * 100.0) < 105,"
    f" then: '{FTP_ZONE_LABELS[3]}',"
    "when: (activities.weighted_avg_watts / activities.ftp_ref * 100.0) < 120,"
    f" then: '{FTP_ZONE_LABELS[4]}',"
    f" else: '{FTP_ZONE_LABELS[5]}')"
)

_CADENCE_CASE = (
    "case("
    "when: activities.avg_cadence < 70, then: '{}',"
    "when: activities.avg_cadence < 80, then: '{}',"
    "when: activities.avg_cadence < 90, then: '{}',"
    "when: activities.avg_cadence < 100, then: '{}',"
    " else: '{}')"
).format(*CADENCE_BUCKETS)


@st.cache_resource
def get_client() -> AnfraClient:
    """Shared MCP client (the server owns the DuckDB lock — always go through it)."""
    return AnfraClient.from_env(dataset=DATASET)


def _frame(res) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    return res.frame()


def _types_filter(types: tuple[str, ...]) -> list[Filter | str]:
    return [is_in("activities.ride_type", list(types))] if types else []


def _win(dim: str, date_from: str, date_to: str) -> Filter:
    return between(dim, date_from, date_to)


# ---------------------------------------------------------------------------
# Metadata + KPI strip
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def date_bounds() -> tuple[dt.date, dt.date]:
    """(earliest, latest) ride dates — .sql() passthrough (min/max bounds)."""
    res = get_client().sql(
        "SELECT MIN(CAST(start_local AS DATE)) AS lo,"
        " MAX(CAST(start_local AS DATE)) AS hi FROM activities"
        " WHERE ride_type IS NOT NULL",
        data_source=DATA_SOURCE,
    )
    row = _frame(res).iloc[0]
    return dt.date.fromisoformat(str(row["lo"])[:10]), dt.date.fromisoformat(str(row["hi"])[:10])


@st.cache_data(ttl=300)
def kpi_ftp() -> pd.DataFrame:
    """K1 — current FTP: ftp_ref of the most recent ride (§8.1). Empty = case 3."""
    res = get_client().query(
        dimensions=[("day", "activities.date"), ("ftp_w", "activities.ftp_ref")],
        filters=[RIDES],
        order_by=["day desc"],
        page=1,
        page_size=1,
        timezone=TIMEZONE,
    )
    return _frame(res)[["ftp_w"]]


@st.cache_data(ttl=300)
def kpi_ride_km_week(types: tuple[str, ...], today: dt.date | None = None) -> pd.DataFrame:
    """K2 — this ISO week's ride km vs mean of the 4 preceding complete weeks (D13)."""
    today = today or dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    mondays = [monday - dt.timedelta(days=7 * i) for i in range(5)]
    res = get_client().query(
        dimensions=["activities.week_start"],
        measures={"km": "ride_distance_km"},
        filters=[
            between("activities.week_start", mondays[-1].isoformat(), mondays[0].isoformat()),
            RIDES,
            *_types_filter(types),
        ],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    df = _frame(res)
    by_week = {pd.Timestamp(w).date(): (0.0 if pd.isna(km) else float(km)) for w, km in df.values}
    this_week = by_week.get(monday, 0.0)
    avg_4wk = sum(by_week.get(m, 0.0) for m in mondays[1:]) / 4.0
    return pd.DataFrame({"this_week_km": [this_week], "avg_4wk_km": [avg_4wk]})


@st.cache_data(ttl=300)
def kpi_elev_90d(types: tuple[str, ...], today: dt.date | None = None) -> pd.DataFrame:
    """K3 — Σ elev gain + Σ km over rides in the last 90 days (wall clock)."""
    today = today or dt.date.today()
    res = get_client().query(
        measures={"elev_gain_m": "ride_elev_gain_m", "km": "ride_distance_km"},
        filters=[
            between(
                "activities.date",
                (today - dt.timedelta(days=89)).isoformat(),
                today.isoformat(),
            ),
            RIDES,
            *_types_filter(types),
        ],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def kpi_if_90d(types: tuple[str, ...], today: dt.date | None = None) -> pd.DataFrame:
    """K4 — duration-weighted mean IF over rides with power, last 90 d (§8.3)."""
    today = today or dt.date.today()
    res = get_client().query(
        measures={
            "if_mean": "ride_intensity_factor",
            "rides_with_power": "ride_activities",
        },
        filters=[
            between(
                "activities.date",
                (today - dt.timedelta(days=89)).isoformat(),
                today.isoformat(),
            ),
            RIDES,
            POWER,
            *_types_filter(types),
        ],
        timezone=TIMEZONE,
    )
    return _frame(res)


# ---------------------------------------------------------------------------
# C1 / C2 — weekly grain
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def fitness_trend(date_from: str, date_to: str) -> pd.DataFrame:
    """C1 — CTL/ATL/TSB weekly, earliest week → window end (D9: date_from ignored)."""
    res = get_client().query(
        dimensions=["weekly_summary.week_start"],
        measures=["weekly_summary.ctl", "weekly_summary.atl", "weekly_summary.tsb"],
        filters=[f"weekly_summary.week_start <= @{date_to}"],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def weekly_load_ramp(date_from: str, date_to: str) -> pd.DataFrame:
    """C2 — weekly cycling load + ramp (§8.7 in-window diff, first week gap)."""
    res = get_client().query(
        dimensions=["weekly_by_category.week_start"],
        measures={"load": "cycling_load"},
        filters=[
            between("weekly_by_category.week_start", date_from, date_to),
            "weekly_by_category.category in ['Ride']",
        ],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    df = _frame(res)
    df["ramp"] = df["load"].diff()
    return df


# ---------------------------------------------------------------------------
# C3–C6 — volume & consistency
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def weekly_ride_distance(date_from: str, date_to: str) -> pd.DataFrame:
    """C3 — weekly ride km + weekly elevation gain."""
    res = get_client().query(
        dimensions=["activities.week_start"],
        measures={"ride_km": "ride_distance_km", "elev_gain_m": "ride_elev_gain_m"},
        filters=[_win("activities.date", date_from, date_to), RIDES],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def ride_calendar(date_from: str, date_to: str) -> pd.DataFrame:
    """C4 — daily ride km (the app pivots to weekday × ISO-week grid)."""
    res = get_client().query(
        dimensions=[("day", "activities.date")],
        measures={"km": "ride_distance_km"},
        filters=[_win("activities.date", date_from, date_to), RIDES],
        order_by=["day asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def ride_mix(date_from: str, date_to: str) -> pd.DataFrame:
    """C5 — hours by ride type (cross-filter SOURCE; date-only by design)."""
    res = get_client().query(
        dimensions=["activities.ride_type"],
        measures={"hours": "ride_time_h"},
        filters=[_win("activities.date", date_from, date_to), RIDES],
        order_by=["hours desc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def weekly_hours_by_type(date_from: str, date_to: str) -> pd.DataFrame:
    """C6 — weekly hours per ride type (weekly grain per §7-C6: date-only)."""
    res = get_client().query(
        dimensions=["activities.week_start", "activities.ride_type"],
        measures={"hours": "ride_time_h"},
        filters=[_win("activities.date", date_from, date_to), RIDES],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


# ---------------------------------------------------------------------------
# C7–C9 — power
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def rides_with_power(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """Caption counts for power components: (rides with power, all rides)."""
    res = get_client().query(
        measures={
            "with_power": "activities.activity_count | where(activities.weighted_avg_watts > 0)",
            "total": "ride_activities",
        },
        filters=[_win("activities.date", date_from, date_to), RIDES, *_types_filter(types)],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def power_zones_weekly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C7 — weekly moving hours per %FTP zone (§8.2 left-inclusive buckets)."""
    res = get_client().query(
        custom_dimensions={"activities.power_zone": _ZONE_CASE},
        dimensions=[("week_start", "activities.week_start"), ("zone", "activities.power_zone")],
        measures={"hours": "ride_time_h"},
        filters=[_win("activities.date", date_from, date_to), RIDES, POWER, *_types_filter(types)],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def intensity_trend(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C8 — monthly duration-weighted IF and mean %FTP (§8.2/§8.3)."""
    res = get_client().query(
        dimensions=["activities.month"],
        measures={"if_mean": "ride_intensity_factor", "pct_ftp": "ride_pct_ftp"},
        filters=[_win("activities.date", date_from, date_to), RIDES, POWER, *_types_filter(types)],
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def power_weight_weekly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C9 — weekly mean watts + W/kg; two queries outer-merged (weight-only gaps)."""
    base = [_win("activities.date", date_from, date_to), RIDES, *_types_filter(types)]
    watts_res = get_client().query(
        dimensions=["activities.week_start"],
        measures={"watts": "ride_avg_watts"},
        filters=[*base, POWER],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    wkg_res = get_client().query(
        dimensions=["activities.week_start"],
        measures={"w_per_kg": "ride_w_per_kg"},
        filters=[*base, POWER, "activities.weight_ref_kg is not null"],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    watts, wkg = _frame(watts_res), _frame(wkg_res)
    return (
        watts.merge(wkg, on="week_start", how="outer")
        .sort_values("week_start")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# C10–C15 — speed & cadence
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def speed_by_type_monthly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C10 — monthly true speed (§8.8) per ride type, ≥1 km rides, gaps kept."""
    res = get_client().query(
        dimensions=["activities.month", "activities.ride_type"],
        measures={"speed_kmh": "ride_speed_kmh"},
        filters=[
            _win("activities.date", date_from, date_to),
            RIDES,
            f"activities.distance_m >= {MIN_RIDE_M}",
            *_types_filter(types),
        ],
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def cadence_by_type_monthly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C11 — monthly duration-weighted cadence (§8.4 guard) per ride type."""
    res = get_client().query(
        dimensions=["activities.month", "activities.ride_type"],
        measures={"rpm": "ride_weighted_cadence"},
        filters=[
            _win("activities.date", date_from, date_to),
            RIDES,
            CADENCE,
            *_types_filter(types),
        ],
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def cadence_buckets_weekly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C12 — weekly hours in cadence buckets (edges per D6), cadence rides only."""
    res = get_client().query(
        custom_dimensions={"activities.cadence_bucket": _CADENCE_CASE},
        dimensions=[
            ("week_start", "activities.week_start"),
            ("bucket", "activities.cadence_bucket"),
        ],
        measures={"hours": "ride_time_h"},
        filters=[
            _win("activities.date", date_from, date_to),
            RIDES,
            CADENCE,
            *_types_filter(types),
        ],
        order_by=["week_start asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def cadence_vs_speed(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C13 — per-ride scatter source: speed vs cadence (§8.4 guard, D7)."""
    res = get_client().query(
        custom_dimensions={
            "activities.speed_kmh": "activities.avg_speed_ms * 3.6",
        },
        dimensions=[
            ("day", "activities.date"),
            ("name", "activities.name"),
            "activities.ride_type",
            ("speed_kmh", "activities.speed_kmh"),
            ("cadence", "activities.avg_cadence"),
        ],
        filters=[
            _win("activities.date", date_from, date_to),
            RIDES,
            CADENCE,
            "activities.avg_speed_ms is not null",
            *_types_filter(types),
        ],
        order_by=["day asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def hilliness_by_type_monthly(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C14 — monthly Σelev/Σdist×1000 (§8.6) per ride type, ≥1 km rides."""
    res = get_client().query(
        dimensions=["activities.month", "activities.ride_type"],
        measures={"elev_per_km": "ride_elev_per_km"},
        filters=[
            _win("activities.date", date_from, date_to),
            RIDES,
            f"activities.distance_m >= {MIN_RIDE_M}",
            "activities.elev_gain_m is not null",
            *_types_filter(types),
        ],
        order_by=["month asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def speed_by_temp(date_from: str, date_to: str, types: tuple[str, ...]) -> pd.DataFrame:
    """C15 — mean speed (§8.8) per 5 °C bucket, floored at −5 °C; rides with temp."""
    res = get_client().query(
        custom_dimensions={
            "activities.temp_bucket_low": (
                f"case(when: floor(activities.avg_temp_c / {TEMP_BUCKET_STEP_C})"
                f" * {TEMP_BUCKET_STEP_C} < {TEMP_FLOOR_C},"
                f" then: {TEMP_FLOOR_C},"
                f" else: floor(activities.avg_temp_c / {TEMP_BUCKET_STEP_C})"
                f" * {TEMP_BUCKET_STEP_C})"
            )
        },
        dimensions=[("bucket_low", "activities.temp_bucket_low")],
        measures={"speed_kmh": "ride_speed_kmh", "rides": "ride_activities"},
        filters=[
            _win("activities.date", date_from, date_to),
            RIDES,
            "activities.avg_temp_c is not null",
            *_types_filter(types),
        ],
        order_by=["bucket_low asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


# ---------------------------------------------------------------------------
# C16–C17 — endurance (long rides; intervals.icu-provided decoupling §8.9)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def long_ride_decoupling(date_from: str, date_to: str) -> pd.DataFrame:
    """C16 — decoupling % per long ride (§4); date-only filter by design."""
    res = get_client().query(
        dimensions=[
            ("day", "activities.date"),
            ("name", "activities.name"),
            ("decoupling_pct", "activities.hr_decoupling"),
        ],
        filters=[
            _win("activities.date", date_from, date_to),
            RIDES,
            f"activities.moving_time_s >= {LONG_RIDE_MIN_S}",
            "activities.hr_decoupling is not null",
        ],
        order_by=["day asc"],
        timezone=TIMEZONE,
    )
    return _frame(res)


@st.cache_data(ttl=300)
def decoupling_by_type(date_from: str, date_to: str) -> pd.DataFrame:
    """C17 — mean decoupling per ride type over long rides + qualifying counts."""
    res = get_client().query(
        dimensions=["activities.ride_type"],
        measures={
            "avg_decoupling": "(activities | avg(activities.hr_decoupling))",
            "long_rides": "ride_activities",
        },
        filters=[
            _win("activities.date", date_from, date_to),
            RIDES,
            f"activities.moving_time_s >= {LONG_RIDE_MIN_S}",
            "activities.hr_decoupling is not null",
        ],
        order_by=["avg_decoupling desc"],
        timezone=TIMEZONE,
    )
    return _frame(res)
