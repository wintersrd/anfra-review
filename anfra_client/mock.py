"""Scripted transport for hermetic tests.

``MockTransport`` replays recorded/fake responses and records every request,
so tests can assert the exact JSON-RPC payloads the client produces (session
handling, filter shapes, pagination) without a running server.

Typical use::

    t = MockTransport()
    t.script_initialize(session_id="mock-sid")
    t.script_tool("core.query", [fixture("query_success")])
    cx = AnfraClient(url="mock://", dataset="running_analytics", transport=t)
    result = cx.aql("explore { ... }")
    assert t.requests[0].method == "initialize"
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from anfra_client.transport import TransportResponse, sse_body

Matcher = Callable[[dict], bool]
Responder = Callable[[dict], "str | TransportResponse | None"]


@dataclass
class RecordedRequest:
    payload: dict
    session_id: str | None

    @property
    def method(self) -> str:
        return str(self.payload.get("method", ""))

    @property
    def id(self):  # type: ignore[no-untyped-def]
        return self.payload.get("id")

    @property
    def arguments(self) -> dict:
        """tools/call arguments."""
        return self.payload.get("params", {}).get("arguments", {})

    @property
    def tool(self) -> str:
        return self.payload.get("params", {}).get("name", "")


class MockTransport:
    """Records requests; answers from scripted routes (last matching wins).

    Requests without any matching route get a protocol-minimal default:
    ``initialize`` is answered with a fresh session id (so handshake tests
    don't need scripting), ``notifications/*`` get 202, everything else gets
    500 — which surfaces as :class:`AnfraConnectionError` in the client.
    """

    def __init__(self, session_counter_start: int = 1) -> None:
        self.requests: list[RecordedRequest] = []
        self._routes: list[tuple[Matcher, Responder]] = []
        self._session_counter = session_counter_start

    # -- scripting ----------------------------------------------------------

    def on(self, matcher: Matcher, responder: Responder) -> None:
        """Register a route: ``matcher(payload)`` truthy → ``responder(payload)``."""
        self._routes.append((matcher, responder))

    def script_initialize(self, session_id: str | None = "mock-sid", status: int = 200) -> None:
        body = (
            sse_body(
                {
                    "jsonrpc": "2.0",
                    "id": 0,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {"name": "anfra", "version": "0.0.0-mock"},
                    },
                }
            )
            if session_id is not None
            else ""
        )
        headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def match(payload: dict) -> bool:
            return payload.get("method") == "initialize"

        self.on(match, lambda p: TransportResponse(status, headers, body))

    def script_tool(self, name: str, bodies: list[str], status: int = 200) -> None:
        """Script ``tools/call`` for one tool. Bodies are consumed in order;
        the last one repeats. Each body is raw HTTP text (SSE or JSON)."""
        queue = list(bodies)

        def match(payload: dict) -> bool:
            return (
                payload.get("method") == "tools/call"
                and payload.get("params", {}).get("name") == name
            )

        def respond(payload: dict) -> TransportResponse:
            body = queue.pop(0) if len(queue) > 1 else queue[0]
            return TransportResponse(status, {}, body)

        self.on(match, respond)

    def script_status(self, status: int, body: str = "", headers: dict | None = None) -> None:
        """Answer EVERYTHING with a fixed status (transport-failure tests)."""

        def match(payload: dict) -> bool:
            return True

        self.on(match, lambda p: TransportResponse(status, headers or {}, body))

    # -- Transport protocol -------------------------------------------------

    def post(self, payload: dict, session_id: str | None) -> TransportResponse:
        self.requests.append(RecordedRequest(payload=dict(payload), session_id=session_id))
        if payload.get("method", "").startswith("notifications/"):
            return TransportResponse(202, {}, "")
        for matcher, responder in reversed(self._routes):
            if matcher(payload):
                resp = responder(payload)
                if isinstance(resp, TransportResponse):
                    return resp
                if resp is None:
                    break
                return TransportResponse(200, {}, resp)
        if payload.get("method") == "initialize":
            self._session_counter += 1
            sid = f"mock-session-{self._session_counter - 1}"
            return TransportResponse(
                200,
                {"Mcp-Session-Id": sid},
                sse_body(
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "anfra", "version": "0.0.0-mock"},
                        },
                    }
                ),
            )
        return TransportResponse(
            500,
            {},
            sse_body(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {"code": -32603, "message": "unscripted"},
                }
            ),
        )

    # -- assertions helpers -------------------------------------------------

    def calls(self, method: str) -> list[RecordedRequest]:
        return [r for r in self.requests if r.method == method]

    def tool_calls(self, name: str) -> list[RecordedRequest]:
        return [r for r in self.requests if r.method == "tools/call" and r.tool == name]

    @property
    def session_id(self) -> str | None:
        """Session id used by the most recent non-initialize request."""
        for req in reversed(self.requests):
            if req.method != "initialize":
                return req.session_id
        return None

    def last_payload(self) -> dict:
        return self.requests[-1].payload


def tool_result_body(rpc_id, text_payload: dict) -> str:  # type: ignore[no-untyped-def]
    """Wrap an inner payload (what content[0].text holds) as a tools/call SSE body."""
    return sse_body(
        {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"content": [{"type": "text", "text": json.dumps(text_payload)}]},
        }
    )


def success_payload(fields: list[str], records: list[list], **extra: object) -> dict:
    """A minimal ``core.query`` success payload in the real response shape."""
    payload = {
        "result": {"fields": fields, "records": records},
        "has_more": False,
    }
    payload.update(extra)
    return payload
