"""Shared fixtures for anfra_client tests: fixture loader + mock client."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from anfra_client import AnfraClient  # noqa: E402
from anfra_client.mock import MockTransport, tool_result_body  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    """A recorded real-server response body (SSE text)."""
    return (FIXTURES / f"{name}.sse.txt").read_text()


@pytest.fixture()
def transport() -> MockTransport:
    """Mock wired with real recorded fixtures: handshake, tools, one success."""
    t = MockTransport()
    t.script_initialize(session_id="mock-sid")
    t.script_tool(
        "core.query",
        [
            fixture("query_success"),
            tool_result_body(
                999,
                {
                    "result": {"fields": ["n"], "records": [["1"]]},
                    "has_more": False,
                },
            ),
        ],
    )
    return t


@pytest.fixture()
def client(transport: MockTransport) -> AnfraClient:
    return AnfraClient(url="mock://anfra", dataset="running_analytics", transport=transport)
