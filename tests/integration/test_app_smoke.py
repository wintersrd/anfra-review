"""Full-app smoke test: execute app.py headlessly, capture every chart.

This is the regression net for the two historic breakages: the heatmap block
crashing the whole page (stray helper call) and the apply_layout signature
mismatch that killed everything from "Monthly pace" down. Any structural
change that breaks rendering must fail here.
"""

from __future__ import annotations

import runpy

import pytest
import streamlit as st

pytestmark = pytest.mark.integration

EXPECTED_KEYS = {
    "Fitness trend",
    "Weekly load",
    "Weekly run distance",
    "sport_mix",
    "Daily runs",
    "Weekly hours",
    "Monthly pace",
    "Monthly cadence",
    "Aerobic efficiency",
    "Pace by surface",
    "Stride trend",
    "Hilliness trend",
    "Decoupling by surface",
    "Stride vs pace",
    "Pace blocks",
    "Decoupling trend",
    "Pace by temperature",
}


def test_app_renders_all_charts(repo_root, monkeypatch):
    rendered: list[tuple[str, object]] = []

    def fake_plotly_chart(fig, **kwargs):
        rendered.append((kwargs.get("key", "?"), fig))
        return None  # no selection

    monkeypatch.setattr(st, "plotly_chart", fake_plotly_chart)

    # Prefer recorded MCP responses (server-independent); fall back to the
    # live server when no recordings exist.
    import app_replay
    import queries_aql

    client = app_replay.replay_client()
    if client is None:
        try:
            client = queries_aql.get_client()
            client.ping()
        except Exception:  # noqa: BLE001
            pytest.skip("no replay recordings and anfra serve not reachable")
    monkeypatch.setattr(queries_aql, "get_client", lambda: client)

    runpy.run_path(str(repo_root / "streamlit_app" / "app.py"))

    keys = [k for k, _ in rendered]
    assert len(rendered) == 17, f"expected 17 charts, got {len(rendered)}: {keys}"
    assert len(set(keys)) == len(keys), "duplicate widget keys"
    missing = EXPECTED_KEYS - set(keys)
    assert not missing, f"charts missing from render: {missing}"
    # heatmap regression: the daily-runs figure must actually have data marks
    heatmap = dict(rendered)["Daily runs"]
    assert len(heatmap.data) > 0 and heatmap.data[0].z is not None
