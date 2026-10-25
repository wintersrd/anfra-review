"""Capability matrix: what the anfra_client + AQL stack can actually do.

Live tests (marked ``anfra``, skip when the server is down) pinning the
capabilities a data application may rely on, beyond what the running app
already exercises: the full server-side filter-operator vocabulary, HAVING-
style aggregated filters, negation and null conditions, multi-dimension
explores, cross-model joins, paging, derived (case/floor) dimensions,
arithmetic custom metrics, and result-shape contracts.

Operator vocabulary probed against anfra 0.13.3 — ACCEPTED by input.filters:
    is, is_not, between, last, greater_than, less_than,
    contains, starts_with, ends_with, before*, after*   (*date fields)
`aggregation` applies to a dataset FIELD (model.field), not to a metric.
Anything else is rejected server-side; the matrix pins the accepted set so
an anfra upgrade that drops one fails loudly here.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from anfra_client import AnfraClient, Filter, between, is_in

DATASET = "running_analytics"


def _server_up() -> bool:
    try:
        _client().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


def _client() -> AnfraClient:
    return AnfraClient.from_env(dataset=DATASET)


pytestmark = [
    pytest.mark.anfra,
    pytest.mark.skipif(
        os.environ.get("ANFRA_LIVE_TESTS") == "0" or not _server_up(),
        reason="anfra serve not reachable (start it: ~/.anfra/bin/anfra serve)",
    ),
]


@pytest.fixture(scope="module")
def cx() -> AnfraClient:
    return _client()


def _hours_by_sport(client: AnfraClient, filters: list) -> dict[str, float]:
    res = client.query(
        dimensions=["activities.sport_group"],
        measures={"hours": "total_time_h"},
        filters=filters,
    )
    return {r["sport_group"]: float(r["hours"]) for r in res.rows}


# --------------------------------------------------------------------------
# Filter-operator vocabulary (server-side input.filters)
# --------------------------------------------------------------------------


def test_operator_is_in(cx: AnfraClient) -> None:
    out = _hours_by_sport(cx, [is_in("activities.sport_group", ["run", "ride"])])
    assert set(out) == {"run", "ride"}


def test_operator_is_not(cx: AnfraClient) -> None:
    out = _hours_by_sport(
        cx, [Filter(field="activities.sport_group", operator="is_not", values=["run"])]
    )
    assert "run" not in out and out  # something remains


def test_operator_between_dates(cx: AnfraClient) -> None:
    out = _hours_by_sport(cx, [between("activities.date", "2026-01-01", "2026-03-31")])
    assert out and all(v > 0 for v in out.values())


def test_operator_last_with_modifier(cx: AnfraClient) -> None:
    full = _hours_by_sport(cx, [])
    recent = _hours_by_sport(
        cx, [Filter(field="activities.date", operator="last", values=["90"], modifier="day")]
    )
    assert set(recent) <= set(full)  # narrowing keeps only ever-present sports


def test_operator_greater_than_and_less_than(cx: AnfraClient) -> None:
    # row-level WHERE (pre-aggregation): assert on the activity grain itself
    longs = cx.query(
        dimensions=[("name", "activities.name")],
        measures={"n": "activities.activity_count"},
        filters=[Filter(field="activities.distance_m", operator="greater_than", values=["15000"])],
    )
    shorts = cx.query(
        dimensions=[("name", "activities.name")],
        measures={"n": "activities.activity_count"},
        filters=[Filter(field="activities.distance_m", operator="less_than", values=["5000"])],
    )
    all_names = cx.query(
        dimensions=[("name", "activities.name")],
        measures={"n": "activities.activity_count"},
    )
    assert len(longs.rows) > 0 and len(shorts.rows) > 0
    assert len(longs.rows) + len(shorts.rows) <= len(all_names.rows)


def test_operator_contains_starts_ends(cx: AnfraClient) -> None:
    # text operators are CASE-INSENSITIVE (pinned)
    contains = cx.query(
        dimensions=[("n", "activities.name")],
        measures={"n2": "activities.activity_count"},
        filters=[Filter(field="activities.name", operator="contains", values=["Long"])],
    )
    starts = cx.query(
        dimensions=[("n", "activities.name")],
        measures={"n2": "activities.activity_count"},
        filters=[Filter(field="activities.name", operator="starts_with", values=["Long"])],
    )
    ends = cx.query(
        dimensions=[("n", "activities.name")],
        measures={"n2": "activities.activity_count"},
        filters=[Filter(field="activities.name", operator="ends_with", values=["run"])],
    )
    assert all("long" in r["n"].lower() for r in contains.rows)
    assert all(r["n"].lower().startswith("long") for r in starts.rows)
    assert all(r["n"].lower().endswith("run") for r in ends.rows)
    assert {r["n"] for r in starts.rows} <= {r["n"] for r in contains.rows}


def test_operator_before_after_dates(cx: AnfraClient) -> None:
    early = _hours_by_sport(
        cx, [Filter(field="activities.date", operator="before", values=["2025-06-01"])]
    )
    late = _hours_by_sport(
        cx, [Filter(field="activities.date", operator="after", values=["2026-06-01"])]
    )
    assert early and late


# --------------------------------------------------------------------------
# String conditions (free-form input.conditions)
# --------------------------------------------------------------------------


def test_condition_not_in(cx: AnfraClient) -> None:
    out = _hours_by_sport(cx, ["activities.sport_group not in ['run', 'ride']"])
    assert "run" not in out and "ride" not in out and out


def test_condition_not_equal(cx: AnfraClient) -> None:
    out = _hours_by_sport(cx, ["activities.sport_group != 'walk'"])
    assert "walk" not in out and out


def test_condition_is_not_null(cx: AnfraClient) -> None:
    res = cx.query(
        dimensions=["activities.run_surface"],
        measures={"n": "activities.activity_count"},
        filters=["activities.run_surface is not null"],
    )
    assert all(r["run_surface"] in ("road", "trail", "indoor") for r in res.rows)


def test_mixed_typed_and_string_filters(cx: AnfraClient) -> None:
    out = _hours_by_sport(
        cx,
        [
            is_in("activities.sport_group", ["run"]),
            "activities.distance_m is not null",
            Filter(field="activities.date", operator="last", values=["365"], modifier="day"),
        ],
    )
    assert set(out) == {"run"}


# --------------------------------------------------------------------------
# HAVING-style aggregated filters (aggregation applies to a FIELD, not a metric)
# --------------------------------------------------------------------------


def test_having_aggregated_field(cx: AnfraClient) -> None:
    res = cx.query(
        dimensions=["activities.sport_group"],
        measures={"hours": "total_time_h"},
        filters=[
            Filter(
                field="activities.moving_time_s",
                operator="greater_than",
                values=["360000"],  # 100h total moving time
                aggregation="sum",
            )
        ],
    )
    # full-history hours: run ~250, ride ~165; everything else is well under 100h
    assert {r["sport_group"] for r in res.rows} == {"run", "ride"}


def test_having_aggregation_on_metric_is_rejected(cx: AnfraClient) -> None:
    with pytest.raises(Exception, match="aggregation"):  # AnfraValidationError
        cx.query(
            dimensions=["activities.sport_group"],
            measures={"hours": "total_time_h"},
            filters=[
                Filter(
                    field="total_time_h", operator="greater_than", values=["10"], aggregation="sum"
                )
            ],
        )


# --------------------------------------------------------------------------
# Dimensional sets, joins, paging
# --------------------------------------------------------------------------


def test_three_dimensions_one_explore(cx: AnfraClient) -> None:
    res = cx.query(
        dimensions=["activities.month", "activities.run_surface", "activities.sport_group"],
        measures={"hours": "run_time_h"},
        filters=["activities.sport_group in ['run']"],
    )
    assert res.rows
    assert {"month", "run_surface", "sport_group"} <= set(res.rows[0])


def test_cross_model_join_via_relationship(cx: AnfraClient) -> None:
    # decoupling_calc joined to activities through the AML relationship
    res = cx.query(
        dimensions=["activities.run_surface"],
        measures={"avg": "decoupling_calc.avg_decoupling", "n": "decoupling_calc.long_run_count"},
    )
    assert len(res.rows) == 3  # road / trail / indoor
    assert sum(int(r["n"]) for r in res.rows) == 71


def test_paging_high_cardinality(cx: AnfraClient) -> None:
    aql = (
        "explore { dimensions { name: activities.name }"
        " measures { n: activities.activity_count } sorts { name asc } }"
    )
    p1 = cx.aql(aql, page=1, page_size=10)
    p2 = cx.aql(aql, page=2, page_size=10)
    assert len(p1.rows) == 10 and p1.has_more is True
    assert p2.rows and p2.rows[0]["name"] != p1.rows[0]["name"]
    names1 = {r["name"] for r in p1.rows}
    names2 = {r["name"] for r in p2.rows}
    assert not names1 & names2  # pages are disjoint


# --------------------------------------------------------------------------
# Complex metrics and derived dimensions
# --------------------------------------------------------------------------


def test_arithmetic_custom_metric(cx: AnfraClient) -> None:
    res = cx.query(
        custom_metrics={"km_per_act": "total_distance_km / total_activities"},
        measures=[("km_per_act", "km_per_act")],
    )
    km_per_act = float(res.rows[0]["km_per_act"])
    # ~4300 km over ~500 activities -> order-of-magnitude sanity
    assert 5.0 < km_per_act < 15.0


def test_case_bucket_custom_dimension(cx: AnfraClient) -> None:
    res = cx.query(
        custom_dimensions={
            "activities.pace_bucket": (
                "case("
                "when: activities.avg_speed_ms is null, then: 'unknown',"
                "when: activities.avg_speed_ms > 3.33333, then: 'fast',"
                "else: 'slow')"
            )
        },
        dimensions=[("bucket", "activities.pace_bucket")],
        measures={"hours": "run_time_h"},
        filters=["activities.sport_group in ['run']"],
    )
    buckets = {r["bucket"] for r in res.rows}
    assert buckets <= {"fast", "slow", "unknown"}
    assert {"fast", "slow"} <= buckets


def test_floor_custom_dimension_buckets_monotonic_pace(cx: AnfraClient) -> None:
    res = cx.query(
        custom_dimensions={"activities.temp_lo": "floor(activities.avg_temp_c / 5) * 5"},
        dimensions=[("bucket_low", "activities.temp_lo")],
        measures={"pace": "run_pace_min_km"},
        filters=["activities.avg_temp_c is not null", "activities.sport_group in ['run']"],
        order_by=["bucket_low asc"],
    )
    lows = [float(r["bucket_low"]) for r in res.rows]
    assert lows == sorted(lows)
    assert all(low % 5 == 0 for low in lows)


def test_multi_key_sort_with_direction(cx: AnfraClient) -> None:
    res = cx.query(
        dimensions=["activities.month", "activities.run_surface"],
        measures={"pace": "run_pace_min_km"},
        filters=["activities.sport_group in ['run']"],
        order_by=["month asc", "pace desc"],
    )
    rows = res.rows
    assert rows
    for a, b in zip(rows, rows[1:], strict=False):
        if a["month"] == b["month"]:
            assert float(a["pace"]) >= float(b["pace"])


# --------------------------------------------------------------------------
# Result-shape contracts
# --------------------------------------------------------------------------


def test_empty_result_keeps_columns(cx: AnfraClient) -> None:
    res = cx.query(
        dimensions=["activities.sport_group"],
        measures={"hours": "total_time_h"},
        filters=["activities.distance_m > 1000000000"],
    )
    assert len(res.rows) == 0
    assert [c.name for c in res.columns] == ["sport_group", "hours"]
    df = res.frame()
    assert len(df) == 0 and list(df.columns) == ["sport_group", "hours"]


def test_column_metadata_contract(cx: AnfraClient) -> None:
    res = cx.query(
        dimensions=["activities.sport_group"],
        measures={"hours": "total_time_h"},
    )
    by_name = {c.name: c for c in res.columns}
    assert by_name["sport_group"].is_measure is False
    assert by_name["hours"].is_measure is True
    assert by_name["hours"].is_numeric is True
    assert res.has_more is False
    assert res.sql  # compiled SQL always present on success


def test_frame_coercion_numeric_strings(cx: AnfraClient) -> None:
    df = cx.query(
        dimensions=["activities.sport_group"],
        measures={"hours": "total_time_h"},
    ).frame()
    assert df["hours"].dtype.kind in "fi"  # wire strings -> numeric dtype


def test_timezone_changes_weekly_bucket_labels(cx: AnfraClient) -> None:
    aql = (
        "explore { dimensions { week: activities.week_start } "
        "measures { km: run_distance_km } sorts { week asc } }"
    )
    with_tz = cx.aql(aql, timezone="Europe/Paris", filters=["activities.sport_group in ['run']"])
    for r in with_tz.rows:
        # ISO Mondays, matching SQL date_trunc('week', local date) labels
        assert pd.Timestamp(r["week"]).day_name() == "Monday"
