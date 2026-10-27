"""Full-app gate template: AppTest runs the whole script — zero exceptions.

Lives in tests/integration/. The scenarios are the acceptance criteria, not
decoration: default run, empty window, narrowed filter. ADAPT: file name,
metric labels, component keys.
"""

from __future__ import annotations

import os
from pathlib import Path

import example_data_aql as aql
import pytest
from streamlit.testing.v1 import AppTest

pytestmark = [pytest.mark.integration, pytest.mark.anfra]

# AppTest resolves relative paths against the CALLING file, not the CWD.
APP = Path(__file__).resolve().parents[2] / "streamlit_app" / "example_app.py"
COMPONENT_KEYS = {"kpi_totals", "weekly_distance", "mix_by_surface"}


def _server_up() -> bool:
    try:
        return bool(aql.get_client().ping())
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module", autouse=True)
def _require_server() -> None:
    if os.environ.get("ANFRA_LIVE_TESTS") == "0":
        pytest.skip("live tests disabled (ANFRA_LIVE_TESTS=0)")
    if not _server_up():
        pytest.skip("anfra serve not reachable")


def _fresh_app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120)


def test_app_default_run() -> None:
    at = _fresh_app()
    at.run()
    assert not at.exception
    assert len(at.metric) == 2
    assert at.sidebar.radio[0].value == "Last 90 days"  # the spec default
    assert not [e for e in at.error]  # no component failed
    log = at.session_state["load_log"]
    keys = {row[0] for row in log}
    assert COMPONENT_KEYS <= keys
    assert all(row[2] >= 0 for row in log), f"failed loads: {log}"


def test_app_empty_window() -> None:
    at = _fresh_app()
    at.run()
    at.sidebar.date_input[0].set_value(("2013-01-01", "2013-03-01"))
    at.run()
    assert not at.exception
    assert not [e for e in at.error]


def test_app_surface_filter_narrows() -> None:
    at = _fresh_app()
    at.run()
    at.sidebar.multiselect[0].set_value(["road"])
    at.run()
    assert not at.exception
    log = at.session_state["load_log"]
    by_key = {row[0]: row for row in log}
    assert by_key["weekly_distance"][2] >= 0  # date+surface honored, no crash
    assert by_key["mix_by_surface"][2] >= 0  # date-only source stays alive


def test_app_cross_filter_focus_preseeded() -> None:
    """AppTest cannot click plotly marks; pre-seed the focus state instead.
    An empty AppTest selection is indistinguishable from deselection, so the
    documented behavior is: the pre-seeded focus is CLEARED by the run."""
    at = _fresh_app()
    at.session_state["focus_surface"] = "road"
    at.run()
    assert not at.exception
    assert at.session_state["focus_surface"] is None  # cleared by empty selection
    log = at.session_state["load_log"]
    assert any(row[0] == "weekly_distance" for row in log)
