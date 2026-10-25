"""HTTP transport for the anfra MCP endpoint (streamable HTTP).

The client talks to ``anfra serve``'s MCP endpoint: every call is an HTTP
POST of a JSON-RPC payload; responses arrive either as a bare JSON object or
as an SSE stream of ``data:`` lines (what anfra actually sends). The transport
returns raw ``(status, headers, text)`` so tests can substitute recordings of
real responses.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class TransportError(OSError):
    """Network-level failure (DNS, refused connection, timeout)."""


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    text: str


class Transport(Protocol):
    def post(self, payload: dict, session_id: str | None) -> TransportResponse:
        """POST one JSON-RPC payload; never raises for HTTP error statuses."""
        ...  # pragma: no cover


class UrllibTransport:
    """Default stdlib transport. No dependencies, sync, per-call connection."""

    def __init__(self, url: str, timeout: float = 15.0) -> None:
        self.url = url
        self.timeout = timeout

    def post(self, payload: dict, session_id: str | None) -> TransportResponse:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return TransportResponse(
                    status=resp.status,
                    headers=dict(resp.headers.items()),
                    text=resp.read().decode("utf-8", errors="replace"),
                )
        except urllib.error.HTTPError as exc:  # HTTP errors still carry a body
            return TransportResponse(
                status=exc.code,
                headers=dict(exc.headers.items()) if exc.headers else {},
                text=exc.read().decode("utf-8", errors="replace"),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(str(exc)) from exc


def parse_rpc_responses(text: str, want_id: int) -> dict | None:
    """Extract the JSON-RPC response for ``want_id`` from an SSE or JSON body.

    Streamable HTTP gives each POST its own response stream, so a body
    without our exact id is still unambiguously ours — recorded fixtures
    with historical ids must therefore parse too. Strategy: prefer an exact
    id match, fall back to the first candidate carrying result/error, and
    return None when neither exists (the caller raises a contract error).
    """
    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        whole = None
    candidates: list = [whole] if isinstance(whole, dict) else []
    if not candidates:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data: "):
                try:
                    obj = json.loads(line[len("data: ") :])
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    candidates.append(obj)
    for obj in candidates:
        if obj.get("id") == want_id and ("result" in obj or "error" in obj):
            return obj
    for obj in candidates:
        if "result" in obj or "error" in obj:
            return obj
    return None


def sse_body(obj: dict) -> str:
    """Render a dict the way anfra streams it (used by tests/fixtures)."""
    return "event: message\ndata: " + json.dumps(obj) + "\n"
