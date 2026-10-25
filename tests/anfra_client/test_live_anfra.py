"""Live tests against a running `anfra serve` — the validated MCP contract.

These re-run the operator matrix that was validated empirically against
anfra 0.13.3 (see docs/anfra-client-guide.md). They SKIP when the server is
not reachable, so `pytest -m unit` and CI stay hermetic.
"""

from __future__ import annotations

import os

import pytest

from anfra_client import (
    AnfraClient,
    AnfraCompileError,
    AnfraValidationError,
    between,
    condition,
    is_in,
    last,
)

MARKER = pytest.mark.anfra


def _server_up() -> bool:
    try:
        AnfraClient().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    MARKER,
    pytest.mark.skipif(
        os.environ.get("ANFRA_LIVE_TESTS") == "0" or not _server_up(),
        reason="anfra serve not reachable (start it: ~/.anfra/bin/anfra serve)",
    ),
]

CLIENT = AnfraClient(dataset="running_analytics")
MONTHLY_KM = (
    "explore {\n"
    "  dimensions {\n"
    "    m: activities.month\n"
    "  }\n"
    "  measures {\n"
    "    km: total_distance_km\n"
    "  }\n"
    "  sorts {\n"
    "    m asc\n"
    "  }\n"
    "}"
)


def test_ping_reports_anfra() -> None:
    assert CLIENT.ping().startswith("anfra ")


def test_end_to_end_sport_mix_matches_known_shape() -> None:
    res = CLIENT.aql(
        "explore {\n"
        "  dimensions {\n"
        "    sport: activities.sport_group\n"
        "  }\n"
        "  measures {\n"
        "    hours: total_time_h\n"
        "  }\n"
        "  sorts {\n"
        "    hours desc\n"
        "  }\n"
        "}"
    )
    assert len(res) == 7
    assert res.rows[0]["sport"] == "run"
    assert float(res.rows[0]["hours"]) > 100  # ~250h of running


def test_is_in_filter_is_in_list() -> None:
    all_rows = CLIENT.aql(MONTHLY_KM)
    run_only = CLIENT.aql(MONTHLY_KM, filters=[is_in("activities.sport_group", ["run"])])
    assert len(run_only) < len(all_rows)  # drops ride-only months (Oct 2024)
    assert all(r["km"] is not None for r in run_only.rows)


def test_between_date_filter_narrows_window() -> None:
    res = CLIENT.aql(MONTHLY_KM, filters=[between("activities.date", "2026-06-01", "2026-08-31")])
    months = [r["m"] for r in res.rows]
    assert months == ["2026-06-01", "2026-07-01", "2026-08-01"]


def test_last_filter_with_day_modifier() -> None:
    res = CLIENT.aql(MONTHLY_KM, filters=[last("activities.date", 90, unit="day")])
    assert 1 <= len(res) <= 5  # ~3 monthly buckets in a 90-day window


def test_conditions_and_structured_filters_combine() -> None:
    res = CLIENT.aql(
        MONTHLY_KM,
        filters=[
            is_in("activities.sport_group", ["run"]),
            condition("activities.date matches @(last 90 days)"),
        ],
    )
    assert len(res) >= 1


def test_pagination() -> None:
    page1 = CLIENT.aql(MONTHLY_KM, page=1, page_size=5)
    page2 = CLIENT.aql(MONTHLY_KM, page=2, page_size=5)
    assert len(page1) == 5
    assert page1.rows[0]["m"] != page2.rows[0]["m"]


def test_sql_mode_runs_against_data_source() -> None:
    res = CLIENT.sql("SELECT count(*) AS n FROM activities", data_source="running")
    assert int(res.rows[0]["n"]) == 499  # pinned activity fingerprint


def test_compile_error_raises_with_diagnostics() -> None:
    with pytest.raises(AnfraCompileError) as excinfo:
        CLIENT.aql("explore { measures { x: nope_metric } }")
    assert excinfo.value.diagnostics
    assert excinfo.value.diagnostics[0].get("line") == 1


def test_unknown_filter_field_raises_validation_error() -> None:
    with pytest.raises(AnfraValidationError) as excinfo:
        CLIENT.aql(MONTHLY_KM, filters=[is_in("activities.bogus", ["run"])])
    assert excinfo.value.violations[0]["field"] == "input.filters[0].field"


def test_empty_is_filter_rejected_before_send() -> None:
    # client-side guard short-circuits (server also rejects empty 'is')
    with pytest.raises((ValueError, AnfraValidationError)):
        CLIENT.aql(MONTHLY_KM, filters=[is_in("activities.sport_group", [])])


def test_compile_produces_executable_sql() -> None:
    sql = CLIENT.compile("explore { measures { x: total_distance_km } }")
    assert "SELECT" in sql.upper()
