"""Client behavior against scripted/recorded MCP responses (no server needed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anfra_client import AnfraClient, between, condition, is_in
from anfra_client.errors import (
    AnfraCompileError,
    AnfraConnectionError,
    AnfraContractError,
    AnfraSessionError,
    AnfraValidationError,
)
from anfra_client.mock import MockTransport, success_payload, tool_result_body
from anfra_client.transport import TransportResponse, sse_body

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    """A recorded real-server response body (SSE text)."""
    return (FIXTURES / f"{name}.sse.txt").read_text()


def test_handshake_runs_once_and_session_is_reused(client, transport):
    client.aql("explore { measures { x: total_time_h } }")
    client.aql("explore { measures { x: total_time_h } }")
    assert len(transport.calls("initialize")) == 1
    assert transport.session_id == "mock-sid"
    assert all(r.session_id == "mock-sid" for r in transport.tool_calls("core.query"))
    assert any(r.method == "notifications/initialized" for r in transport.requests)


def test_query_parses_recorded_success(client):
    res = client.aql("explore { measures { x: total_time_h } }")
    assert len(res) == 7
    assert res.fields == ["sport", "hours"]
    first = res.rows[0]
    assert first["sport"] == "run"
    assert first["hours"] == "249.95666666666668"  # raw strings preserved on rows
    assert res.sql  # compiled SQL included in the response
    assert res.has_more is False
    df = res.frame()
    assert df["hours"].iloc[0] == pytest.approx(249.95666666666668)


def test_frame_coerces_numeric_by_column_metadata(client):
    res = client.aql("explore { measures { x: total_time_h } }")
    assert res.frame()["hours"].dtype.kind == "f"
    uncoerced = res.frame(coerce=False)["hours"]
    assert uncoerced.dtype.kind not in "fi"  # strings stay strings when asked


def test_query_renders_explore_and_sends_filters_in_input(client, transport):
    client.query(
        dimensions={"m": "activities.month"},
        measures={"km": "total_distance_km"},
        filters=[
            is_in("activities.sport_group", ["run"]),
            between("activities.date", "2026-01-01", "2026-03-31"),
            condition("activities.date matches @(last 90 days)"),
        ],
        order_by=[("m", "asc")],
        page=2,
        page_size=50,
        timezone="Europe/Paris",
    )
    args = transport.tool_calls("core.query")[0].arguments
    assert args["dataset"] == "running_analytics"
    assert args["query"] == (
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
    inp = args["input"]
    assert inp["filters"] == [
        {"field": "activities.sport_group", "operator": "is", "values": ["run"]},
        {"field": "activities.date", "operator": "between", "values": ["2026-01-01", "2026-03-31"]},
    ]
    assert inp["conditions"] == [{"expr": "activities.date matches @(last 90 days)"}]
    assert args["page"] == 2 and args["page_size"] == 50 and args["timezone"] == "Europe/Paris"


def test_dataset_required():
    cx = AnfraClient(url="mock://", transport=MockTransport())
    with pytest.raises(ValueError, match="dataset"):
        cx.aql("explore { measures { x: m } }")


def test_sql_mode_sends_lang_and_data_source(client, transport):
    client.sql("SELECT count(*) AS n FROM activities", data_source="running")
    args = transport.tool_calls("core.query")[0].arguments
    assert args["lang"] == "sql" and args["data_source"] == "running"


def test_compile_returns_sql_string(client, transport):
    transport.script_tool(
        "core.query.compile",
        [tool_result_body(999, {"sql": "WITH cte AS (SELECT 1)"})],
    )
    assert client.compile("explore { measures { x: total_time_h } }") == "WITH cte AS (SELECT 1)"


def test_ping_reports_server_identity(client):
    assert client.ping() == "anfra 0.0.0-mock"


# -- error mapping -----------------------------------------------------------


def test_compile_error_maps_diagnostics(client, transport):
    transport.script_tool("core.query", [fixture("query_compile_error")])
    with pytest.raises(AnfraCompileError) as excinfo:
        client.aql("explore { measures { x: nope_metric } }")
    assert excinfo.value.diagnostics, "diagnostics list must be attached"
    assert "not defined" in str(excinfo.value)
    assert excinfo.value.diagnostics[0]["line"] == 1


def test_validation_error_maps_violations(client, transport):
    transport.script_tool("core.query", [fixture("query_violation_error")])
    with pytest.raises(AnfraValidationError) as excinfo:
        client.aql(
            "explore { measures { x: total_distance_km } }",
            filters=[is_in("activities.bogus", ["run"])],
        )
    assert excinfo.value.violations[0]["field"] == "input.filters[0].field"
    assert "activities.bogus" in str(excinfo.value)


def test_query_errors_are_never_retried(client, transport):
    transport.script_tool("core.query", [fixture("query_compile_error")])
    with pytest.raises(AnfraCompileError):
        client.aql("explore { measures { x: nope_metric } }")
    assert len(transport.tool_calls("core.query")) == 1


def test_connection_error_retries_then_raises_hint():
    t = MockTransport()
    t.script_status(503, body="overloaded")
    t.script_initialize(session_id="sid")  # registered later → wins for initialize
    cx = AnfraClient(url="mock://", dataset="d", transport=t, max_retries=2)
    with pytest.raises(AnfraConnectionError, match="anfra serve"):
        cx.aql("explore { measures { x: m } }")
    assert len(t.tool_calls("core.query")) == 3  # initial + 2 retries


def test_unreachable_transport_maps_to_connection_error():
    class Dead:
        def post(self, payload, session_id):  # noqa: ANN001
            raise OSError("connection refused")

    cx = AnfraClient(url="mock://", dataset="d", transport=Dead())
    with pytest.raises(AnfraConnectionError, match="connection refused"):
        cx.aql("explore { measures { x: m } }")


def test_stale_session_rehandshakes_once_and_succeeds():
    t = MockTransport()
    state = {"n": 0}

    def responder(payload: dict) -> TransportResponse:
        state["n"] += 1
        if state["n"] == 1:
            return TransportResponse(404, {}, "session expired")
        return TransportResponse(
            200,
            {},
            tool_result_body(payload.get("id"), success_payload(["n"], [["7"]])),
        )

    t.on(lambda p: p.get("method") == "tools/call", responder)
    cx = AnfraClient(url="mock://", dataset="d", transport=t)
    assert len(cx.aql("explore { measures { x: m } }")) == 1
    assert len(t.calls("initialize")) == 2  # original + rehandshake


def test_persistent_session_rejection_raises_session_error():
    t = MockTransport()
    t.on(
        lambda p: p.get("method") == "tools/call",
        lambda p: TransportResponse(404, {}, "session expired"),
    )
    cx = AnfraClient(url="mock://", dataset="d", transport=t)
    with pytest.raises(AnfraSessionError):
        cx.aql("explore { measures { x: m } }")


# -- contract regression tripwires -------------------------------------------


def test_contract_error_on_non_json_content():
    t = MockTransport()
    t.script_initialize()
    t.script_tool("core.query", ["event: message\ndata: not json\n"])
    cx = AnfraClient(url="mock://", dataset="d", transport=t)
    with pytest.raises(AnfraContractError, match="no JSON-RPC response"):
        cx.aql("explore { measures { x: m } }")


def test_contract_error_on_missing_result_fields():
    t = MockTransport()
    t.script_initialize()
    t.script_tool("core.query", [tool_result_body(999, {"unexpected": "shape"})])
    cx = AnfraClient(url="mock://", dataset="d", transport=t)
    with pytest.raises(AnfraContractError, match="fields/records"):
        cx.aql("explore { measures { x: m } }")


def test_contract_error_on_empty_body():
    t = MockTransport()
    t.script_initialize()
    t.script_tool("core.query", [""])
    cx = AnfraClient(url="mock://", dataset="d", transport=t)
    with pytest.raises(AnfraContractError):
        cx.aql("explore { measures { x: m } }")


def test_flat_json_bodies_parse_too():
    """Non-SSE (plain JSON) bodies must work — future-proofing the parser."""
    t = MockTransport()
    t.script_initialize()
    t.script_tool(
        "core.query",
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 999,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(success_payload(["n"], [["7"]]))}
                        ]
                    },
                }
            )
        ],
    )
    cx = AnfraClient(url="mock://", dataset="d", transport=t)
    assert len(cx.aql("explore { measures { x: m } }")) == 1


def test_sse_body_helper_round_trips():
    body = sse_body({"jsonrpc": "2.0", "id": 1, "result": {}})
    assert body.startswith("event: message\ndata: ")


# --------------------------------------------------------------------------
# query(): the structured/logical surface
# --------------------------------------------------------------------------


def _last_call(transport: MockTransport) -> dict:
    return transport.tool_calls("core.query")[-1].arguments


def test_query_str_elems_get_derived_aliases(client, transport):
    client.query(dimensions="activities.sport_group", measures="total_time_h")
    q = _last_call(transport)["query"]
    assert "sport_group: activities.sport_group" in q
    assert "total_time_h: total_time_h" in q
    assert q.startswith("explore {")


def test_query_accepts_tuples_dicts_and_single_values(client, transport):
    client.query(dimensions=("s", "activities.sport_group"), measures={"h": "total_time_h"})
    q = _last_call(transport)["query"]
    assert "s: activities.sport_group" in q
    assert "h: total_time_h" in q
    client.query(dimensions="activities.sport_group", measures="total_time_h")
    q2 = _last_call(transport)["query"]
    assert "sport_group: activities.sport_group" in q2


def test_query_custom_metrics_render_preludes_in_order(client, transport):
    client.query(
        custom_metrics={"m_a": "x | y", "m_b": "z"},
        measures=[("a", "m_a"), ("b", "m_b")],
    )
    q = _last_call(transport)["query"]
    lines = q.splitlines()
    assert lines[0] == "metric m_a = x | y;"
    assert lines[1] == "metric m_b = z;"
    assert "a: m_a" in q and "b: m_b" in q


def test_query_rejects_bad_custom_metric_name(client, transport):
    with pytest.raises(ValueError, match="custom metric name"):
        client.query(custom_metrics={"1bad": "x"}, measures="total_time_h")


def test_query_rejects_duplicate_derived_aliases(client, transport):
    with pytest.raises(ValueError, match="duplicate alias"):
        client.query(dimensions=["a.sport_group", "b.sport_group"], measures="total_time_h")


def test_query_rejects_invalid_alias(client, transport):
    with pytest.raises(ValueError, match="dimensions alias"):
        client.query(dimensions=[("bad-alias", "activities.sport_group")])


def test_query_needs_something_to_render(client, transport):
    with pytest.raises(ValueError, match="at least one dimension or measure"):
        client.query()


def test_query_mixed_filters_route_to_the_right_payload_slots(client, transport):
    client.query(
        measures="total_time_h",
        filters=[
            is_in("activities.sport_group", ["run"]),
            "activities.date matches @(last 90 days)",
            condition("activities.is_race == true"),
        ],
    )
    inp = _last_call(transport)["input"]
    assert inp["filters"] == [
        {"field": "activities.sport_group", "operator": "is", "values": ["run"]}
    ]
    assert inp["conditions"] == [
        {"expr": "activities.date matches @(last 90 days)"},
        {"expr": "activities.is_race == true"},
    ]


def test_query_rejects_unknown_filter_types(client, transport):
    with pytest.raises(TypeError, match="Filter, Condition, or str"):
        client.query(measures="total_time_h", filters=[42])


def test_query_order_by_strings_with_default_direction(client, transport):
    client.query(measures="total_time_h", order_by=["hours desc", "week_start"])
    q = _last_call(transport)["query"]
    assert "hours desc" in q
    assert "week_start asc" in q


def test_query_order_by_rejects_bad_direction(client, transport):
    with pytest.raises(ValueError, match="asc.*desc"):
        client.query(measures="total_time_h", order_by=[("hours", "sideways")])


def test_query_is_explore_false_renders_preludes_only(client, transport):
    client.query(custom_metrics={"m": "total_time_h"}, is_explore=False)
    q = _last_call(transport)["query"]
    assert q == "metric m = total_time_h;"
    assert "explore" not in q


def test_query_is_explore_false_requires_metrics(client, transport):
    with pytest.raises(ValueError, match="custom_metrics"):
        client.query(measures="total_time_h", is_explore=False)


def test_aql_accepts_plain_string_filters(client, transport):
    client.aql("explore { measures { x: total_time_h } }", filters=["a == b"])
    inp = _last_call(transport)["input"]
    assert inp["conditions"] == [{"expr": "a == b"}]
