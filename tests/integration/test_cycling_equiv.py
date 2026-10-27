"""Equivalence: SQL oracle ≡ live AQL layer for the cycling app.

Runs only when ``anfra serve`` answers (skip-with-reason otherwise, or
``ANFRA_LIVE_TESTS=0`` to force-disable). Cases per skill testing reference:
default window, empty window, narrowed (ride-type) filter — every data
function, column names and row content.

Normalization (``_norm``): date-ish strings sliced to 10 chars, numerics
coerced (so 0 == 0.0), NaN/None/empty treated as missing, rows sorted by the
natural key plus numeric columns (duplicate keys pair deterministically).
Rows whose measure columns are ALL missing are dropped on both sides before
compare: the oracle keeps week rows whose only measures are NULL (visual gap
points, e.g. C9 weeks without power), the live layer omits them — identical
charts, different row sets (documented in both layers' docstrings).
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, "streamlit_app")

import cycling_queries as oracle  # noqa: E402
import cycling_queries_aql as aql  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.anfra]

DEFAULT_FROM = "2026-07-08"
DEFAULT_TO = "2026-10-15"
EMPTY = ("2011-01-01", "2011-02-01")
NARROW = ("mtb",)
TODAY = __import__("datetime").date(2026, 10, 26)

_WINDOWS = {
    "default": (DEFAULT_FROM, DEFAULT_TO),
    "empty": EMPTY,
    "narrow": (DEFAULT_FROM, DEFAULT_TO),
}
# functions taking (from, to, types)
_TYPED = [
    aql.rides_with_power,
    aql.power_zones_weekly,
    aql.intensity_trend,
    aql.power_weight_weekly,
    aql.speed_by_type_monthly,
    aql.cadence_by_type_monthly,
    aql.cadence_buckets_weekly,
    aql.cadence_vs_speed,
    aql.hilliness_by_type_monthly,
    aql.speed_by_temp,
]
# wall-clock 90d KPIs taking (types, today)
_KPI90 = [aql.kpi_elev_90d, aql.kpi_if_90d]
# functions taking (from, to)
_PLAIN = [
    aql.fitness_trend,
    aql.weekly_load_ramp,
    aql.weekly_ride_distance,
    aql.ride_calendar,
    aql.ride_mix,
    aql.weekly_hours_by_type,
    aql.long_ride_decoupling,
    aql.decoupling_by_type,
]
_KEY_COLS = {
    "fitness_trend": ["week_start"],
    "weekly_load_ramp": ["week_start"],
    "weekly_ride_distance": ["week_start"],
    "ride_calendar": ["day"],
    "ride_mix": ["ride_type"],
    "weekly_hours_by_type": ["week_start", "ride_type"],
    "long_ride_decoupling": ["day", "name"],
    "decoupling_by_type": ["ride_type"],
    "rides_with_power": [],
    "kpi_ride_km_week": [],
    "kpi_elev_90d": [],
    "kpi_if_90d": [],
    "power_zones_weekly": ["week_start", "zone"],
    "intensity_trend": ["month"],
    "power_weight_weekly": ["week_start"],
    "speed_by_type_monthly": ["month", "ride_type"],
    "cadence_by_type_monthly": ["month", "ride_type"],
    "cadence_buckets_weekly": ["week_start", "bucket"],
    "cadence_vs_speed": ["day", "name"],
    "hilliness_by_type_monthly": ["month", "ride_type"],
    "speed_by_temp": ["bucket_low"],
}


@pytest.fixture(scope="module", autouse=True)
def _require_server():
    if os.environ.get("ANFRA_LIVE_TESTS") == "0":
        pytest.skip("live tests disabled")
    try:
        if not aql.get_client().ping():
            pytest.skip("anfra serve not reachable")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"anfra serve not reachable: {exc}")


@pytest.fixture()
def o(fixture_conn, monkeypatch):
    monkeypatch.setattr(oracle, "get_conn", lambda: fixture_conn)
    for fn in (
        oracle.kpi_elev_90d,
        oracle.kpi_if_90d,
        oracle.rides_with_power,
        oracle.power_zones_weekly,
        oracle.intensity_trend,
        oracle.power_weight_weekly,
        oracle.speed_by_type_monthly,
        oracle.cadence_by_type_monthly,
        oracle.cadence_buckets_weekly,
        oracle.cadence_vs_speed,
        oracle.hilliness_by_type_monthly,
        oracle.speed_by_temp,
        oracle.fitness_trend,
        oracle.weekly_load_ramp,
        oracle.weekly_ride_distance,
        oracle.ride_calendar,
        oracle.ride_mix,
        oracle.weekly_hours_by_type,
        oracle.long_ride_decoupling,
        oracle.decoupling_by_type,
        oracle.kpi_ride_km_week,
    ):
        fn.clear()
    return oracle


def _norm(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    if len(df) == 0:
        return df
    value_cols = [c for c in df.columns if c not in key_cols]
    if value_cols:  # drop rows whose measures are all missing (gap-point rows)
        df = df.dropna(subset=value_cols, how="all")
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str).str[:10]
        elif df[col].dtype == object:
            df[col] = (
                df[col]
                .astype(str)
                .str[:10]
                .where(df[col].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}"), df[col])
            )
            # numeric-looking strings stay numeric
            num = pd.to_numeric(df[col], errors="coerce")
            df[col] = df[col].where(num.isna(), num)
    df = df.sort_values(df.columns.tolist()).reset_index(drop=True)
    return df


def _assert_equal(live: pd.DataFrame, orac: pd.DataFrame, key_cols: list[str], label: str):
    lv, ov = _norm(live, key_cols), _norm(orac, key_cols)
    assert list(lv.columns) == list(ov.columns), (
        f"{label}: columns {list(lv.columns)} != {list(ov.columns)}"
    )
    pd.testing.assert_frame_equal(
        lv,
        ov,
        check_dtype=False,
        check_exact=False,
        rtol=1e-9,
        atol=1e-9,
        obj=label,
    )


def test_constants_pinned_between_layers():
    for name in (
        "RIDE_TYPES",
        "FTP_ZONE_LABELS",
        "FTP_ZONE_EDGES",
        "CADENCE_BUCKETS",
        "CADENCE_EDGES",
        "LONG_RIDE_MIN_S",
        "CADENCE_MIN_RPM",
        "MIN_RIDE_M",
        "TEMP_BUCKET_STEP_C",
        "TEMP_FLOOR_C",
    ):
        assert getattr(oracle, name) == getattr(aql, name), name


@pytest.mark.parametrize("fn", _TYPED, ids=lambda fn: fn.__name__)
@pytest.mark.parametrize("label", ["default", "empty", "narrow"])
def test_typed_functions_equivalent(o, fn, label):
    frm, to = _WINDOWS[label]
    types = NARROW if label == "narrow" else ()
    live = fn(frm, to, types)
    orac = getattr(o, fn.__name__)(frm, to, types)
    _assert_equal(live, orac, _KEY_COLS[fn.__name__], f"{fn.__name__}[{label}]")


@pytest.mark.parametrize("fn", _KPI90, ids=lambda fn: fn.__name__)
@pytest.mark.parametrize("types", [(), NARROW], ids=["all", "narrow"])
def test_kpi90_functions_equivalent(o, fn, types):
    _assert_equal(
        fn(types, TODAY),
        getattr(o, fn.__name__)(types, TODAY),
        _KEY_COLS[fn.__name__],
        f"{fn.__name__}[{types}]",
    )


@pytest.mark.parametrize("fn", _PLAIN, ids=lambda fn: fn.__name__)
@pytest.mark.parametrize("label", ["default", "empty"])
def test_plain_functions_equivalent(o, fn, label):
    frm, to = _WINDOWS[label]
    _assert_equal(
        fn(frm, to),
        getattr(o, fn.__name__)(frm, to),
        _KEY_COLS[fn.__name__],
        f"{fn.__name__}[{label}]",
    )


def test_kpi_ride_km_week_equivalent(o):
    _assert_equal(
        aql.kpi_ride_km_week((), TODAY),
        o.kpi_ride_km_week((), TODAY),
        _KEY_COLS["kpi_ride_km_week"],
        "kpi_ride_km_week",
    )


def test_kpi_ftp_equivalent(o):
    assert float(aql.kpi_ftp().iloc[0]["ftp_w"]) == float(o.kpi_ftp().iloc[0]["ftp_w"])
