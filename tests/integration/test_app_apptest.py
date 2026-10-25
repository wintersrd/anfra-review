"""Full-app execution via Streamlit's AppTest against the live anfra server.

The end-to-end check an HTTP health probe cannot give: Streamlit only executes
the app script when a real session connects, so `curl 200` says nothing about
whether the script runs (this exact gap shipped a dead app once — the AQL flip
round's server looked healthy while every browser session hit
ModuleNotFoundError because anfra_client/ was not on sys.path).

app.py executes all 22 data-layer queries against the live server here.
Requires `anfra serve`; skips like the other live tests when it is down.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _server_up() -> bool:
    if os.environ.get("ANFRA_LIVE_TESTS") == "0":
        return False
    try:
        from anfra_client import AnfraClient

        AnfraClient().ping()
        return True
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        return False


pytestmark = [
    pytest.mark.anfra,
    pytest.mark.skipif(not _server_up(), reason="anfra serve not reachable"),
]


def test_app_executes_end_to_end() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(
        str(ROOT / "streamlit_app" / "app.py"),
        default_timeout=120,
    )
    at.run()

    assert not at.exception, "\n".join(e.message for e in at.exception)
    assert len(at.metric) == 4, "KPI strip should render 4 metrics"
    assert at.sidebar.radio, "date-preset radio should exist"
