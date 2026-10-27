"""Full-app execution via Streamlit's AppTest for cycling_app.py.

The end-to-end gate from the spec (§9): the whole script runs with ZERO
exceptions on the default window, an empty window, a narrowed ride-type
filter, and with the donut cross-filter pre-seeded. Also asserts the load
log records every expected query, none failed (rows == -1), and no st.error
was rendered.

Requires `anfra serve` (env ANFRA_MCP_URL); skips with a reason otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_LOAD_LOG_KEYS = [
    "date_bounds",
    "kpi_ftp",
    "kpi_ride_km_week",
    "kpi_elev_90d",
    "kpi_if_90d",
    "fitness_trend",
    "weekly_load_ramp",
    "weekly_ride_distance",
    "ride_calendar",
    "ride_mix",
    "weekly_hours_by_type",
    "rides_with_power",
    "power_zones_weekly",
    "intensity_trend",
    "power_weight_weekly",
    "speed_by_type_monthly",
    "cadence_by_type_monthly",
    "cadence_buckets_weekly",
    "cadence_vs_speed",
    "hilliness_by_type_monthly",
    "speed_by_temp",
    "long_ride_decoupling",
    "decoupling_by_type",
]


def _server_up() -> bool:
    if os.environ.get("ANFRA_LIVE_TESTS") == "0":
        return False
    try:
        from anfra_client import AnfraClient

        return bool(AnfraClient.from_env().ping())
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.anfra,
    pytest.mark.skipif(not _server_up(), reason="anfra serve not reachable"),
]


def _run_app() -> Any:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "streamlit_app" / "cycling_app.py"), default_timeout=120)
    at.run()
    return at


def _assert_healthy(at) -> None:  # type: ignore[no-untyped-def]
    assert not at.exception, "\n".join(e.message for e in at.exception)
    assert not at.error, "\n".join(str(e.value) for e in at.error)
    log = at.session_state.get("load_log", [])
    assert log, "load log should record queries"
    keys = [entry[0] for entry in log]
    for key in EXPECTED_LOAD_LOG_KEYS:
        assert key in keys, f"load log missing {key}"
    failed = [entry for entry in log if entry[2] == -1]
    assert not failed, f"failed loads: {failed}"
    assert len(at.metric) == 4, "KPI strip should render 4 metrics"
    assert at.sidebar.radio, "date-preset radio should exist"


def test_default_window_full_app() -> None:
    at = _run_app()
    _assert_healthy(at)
    # K1 shows the configured FTP; window is data-relative Last 90 days
    assert "250" in at.metric[0].value
    # K4 renders a real IF value in the default window (10 power rides)
    assert "0.76" in at.metric[3].value


def test_empty_window_friendly() -> None:
    at = _run_app()
    _assert_healthy(at)
    # narrow the window to 2011 via the date_input widget
    at.date_input(key="date_range").set_value(
        (
            at.session_state["date_range"][0].replace(year=2011, month=1, day=1),
            at.session_state["date_range"][1].replace(year=2011, month=2, day=1),
        )
    )
    at.run()
    assert not at.exception
    assert not at.error
    log = at.session_state.get("load_log", [])
    assert all(entry[2] != -1 for entry in log)


def test_narrowed_filter_virtual_only() -> None:
    at = _run_app()
    _assert_healthy(at)
    at.multiselect(key="ride_types").set_value(["virtual"])
    at.run()
    _assert_healthy(at)
    # K3 elevation: virtual trainer rides record no GPS → friendly empty
    assert "—" in at.metric[2].value
    # cross-filter banner absent (multiselect path, not donut click)
    assert not any("Cross-filter active" in str(i.value) for i in at.info)


def test_cross_filter_preseeded_and_cleared() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "streamlit_app" / "cycling_app.py"), default_timeout=120)
    at.session_state["focus_ride_type"] = "road"
    at.run()
    _assert_healthy(at)
    assert any("Cross-filter active" in str(i.value) for i in at.info)
    at.button[0].click()  # Clear cross-filter
    at.run()
    _assert_healthy(at)
    assert not any("Cross-filter active" in str(i.value) for i in at.info)
