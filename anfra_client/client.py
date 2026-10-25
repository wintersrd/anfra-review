"""AnfraClient — a small, abstracted Python consumer of anfra's MCP server.

anfra (``anfra serve``) is the infrastructure backend: database, semantic
model (AML), and query engine. This client lets a Python data app express
logical query elements — dimensions, measures, filters — and get rows back,
without writing SQL or managing the DuckDB file.

Quickstart::

    from anfra_client import AnfraClient, is_in, between, last

    cx = AnfraClient.from_env(dataset="running_analytics")

    result = cx.query(
        dimensions={"sport": "activities.sport_group"},
        measures={"hours": "total_time_h"},
        filters=[is_in("activities.sport_group", ["run", "trail"])],
        order_by=[("hours", "desc")],
    )
    df = result.frame()          # pandas DataFrame, numerics coerced
    for row in result.rows: ...  # list[dict]

Error handling: every failure raises a subclass of :class:`~anfra_client.errors.AnfraError`
with a ``hint``. Connection errors mean ``anfra serve`` is likely down;
compile/validation errors carry the server's diagnostics; contract errors
mean the anfra MCP envelope changed (pin your anfra version).
"""

from __future__ import annotations

import json
import os
import threading
import time

from anfra_client.errors import (
    AnfraCompileError,
    AnfraConnectionError,
    AnfraContractError,
    AnfraError,
    AnfraQueryError,
    AnfraSessionError,
    AnfraValidationError,
)
from anfra_client.models import Column, Condition, Filter, QueryResult
from anfra_client.transport import (
    Transport,
    TransportError,
    TransportResponse,
    UrllibTransport,
    parse_rpc_responses,
)

__all__ = ["AnfraClient"]

_DEFAULT_URL = "http://127.0.0.1:7878/mcp"
_RETRYABLE_STATUSES = {500, 502, 503, 504}


class AnfraClient:
    """Sync MCP client for one anfra server. Thread-safe (Streamlit reruns)."""

    def __init__(
        self,
        url: str = _DEFAULT_URL,
        dataset: str | None = None,
        timeout: float = 15.0,
        transport: Transport | None = None,
        max_retries: int = 2,
        client_name: str = "anfra-client",
    ) -> None:
        self.url = url
        self.dataset = dataset
        self._transport = (
            transport if transport is not None else UrllibTransport(url, timeout=timeout)
        )
        self._max_retries = max_retries
        self._client_name = client_name
        self._lock = threading.Lock()
        self._session_id: str | None = None
        self._next_id = 1
        self.server_info: dict = {}

    # -- construction -------------------------------------------------------

    @classmethod
    def from_env(cls, dataset: str | None = None, **kw: object) -> AnfraClient:
        """URL from ``ANFRA_MCP_URL`` (default http://127.0.0.1:7878/mcp)."""
        return cls(url=os.environ.get("ANFRA_MCP_URL", _DEFAULT_URL), dataset=dataset, **kw)  # type: ignore[arg-type]

    # -- low-level JSON-RPC -------------------------------------------------

    def _id(self) -> int:
        with self._lock:
            rpc_id = self._next_id
            self._next_id += 1
        return rpc_id

    def _handshake(self) -> None:
        rpc_id = self._id()
        payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": self._client_name, "version": "1.0.0"},
            },
        }
        try:
            resp = self._post_once(payload, session_id=None)
        except (TransportError, OSError) as exc:
            raise AnfraConnectionError(
                f"could not reach anfra at {self.url}: {exc}",
                hint="Is `anfra serve` running? (start it in the repo: ~/.anfra/bin/anfra serve)",
            ) from exc
        session_id = next(
            (v for k, v in resp.headers.items() if k.lower() == "mcp-session-id"), None
        )
        if not session_id:
            raise AnfraContractError(
                "initialize response carried no Mcp-Session-Id header",
                hint="The endpoint may not be an MCP server — check the anfra serve URL.",
            )
        body = parse_rpc_responses(resp.text, rpc_id)
        info: dict = {}
        if body and isinstance(body.get("result"), dict):
            info = body["result"].get("serverInfo", {}) or {}
        else:
            raise AnfraContractError("initialize response was not a valid JSON-RPC result")
        with self._lock:
            self._session_id = session_id
            self.server_info = info
        # notify — best effort, no response expected
        try:
            self._transport.post(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id
            )
        except TransportError:
            pass

    def _post_once(self, payload: dict, session_id: str | None) -> TransportResponse:
        return self._transport.post(payload, session_id)

    def _rpc(self, payload: dict) -> dict:
        """Send one JSON-RPC request with retries and one session re-init.

        Returns the full JSON-RPC response object. Raises AnfraConnectionError
        for unreachable/5xx-after-retries, AnfraSessionError if a re-init was
        attempted and still failed, AnfraContractError if no matching response.
        """
        rpc_id = payload.get("id")
        assert rpc_id is not None
        if self._session_id is None and payload.get("method") != "initialize":
            self._handshake()

        session_retried = False
        attempt = 0
        while True:
            try:
                resp = self._post_once(payload, self._session_id)
            except (TransportError, OSError) as exc:
                if attempt < self._max_retries:
                    time.sleep(0.25 * (2**attempt))
                    attempt += 1
                    continue
                raise AnfraConnectionError(
                    f"could not reach anfra at {self.url}: {exc}",
                    hint="Is `anfra serve` running? (repo root: ~/.anfra/bin/anfra serve)",
                ) from exc

            if resp.status in _RETRYABLE_STATUSES and attempt < self._max_retries:
                time.sleep(0.25 * (2**attempt))
                attempt += 1
                continue
            if resp.status >= 400:
                if resp.status in (400, 404) and payload.get("method") != "initialize":
                    if not session_retried:
                        # stale/unknown session — rehandshake once and retry
                        session_retried = True
                        try:
                            self._handshake()
                            continue
                        except AnfraError as exc:
                            raise AnfraSessionError(
                                f"anfra rejected the MCP session (HTTP {resp.status})"
                                " and re-initialization failed",
                                hint="Restart `anfra serve`.",
                            ) from exc
                    raise AnfraSessionError(
                        f"anfra repeatedly rejected the MCP session (HTTP {resp.status})",
                        hint="The server is dropping sessions — is `anfra serve` crash-looping?",
                    )
                raise AnfraConnectionError(
                    f"anfra answered HTTP {resp.status}: {resp.text[:200]}",
                    hint="Check the anfra serve process and URL."
                    if resp.status >= 500
                    else "The request was rejected before execution — see message.",
                )

            body = parse_rpc_responses(resp.text, rpc_id)
            if body is None:
                raise AnfraContractError(
                    f"no JSON-RPC response with id={rpc_id} in reply from {self.url}",
                    hint="If this started after an anfra upgrade, the MCP envelope"
                    " changed — pin the anfra version.",
                )
            return body

    # -- MCP surface --------------------------------------------------------

    def initialize(self) -> dict:
        """Run the MCP handshake now; returns serverInfo."""
        self._handshake()
        return self.server_info

    def tools_list(self) -> list[dict]:
        body = self._rpc({"jsonrpc": "2.0", "id": self._id(), "method": "tools/list"})
        result = body.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise AnfraContractError("tools/list response missing result.tools[]")
        return result["tools"]

    def ping(self) -> str:
        """Server identity string ("anfra 0.13.3"); cheap health check."""
        try:
            info = self.server_info or self.initialize()
        except AnfraError:
            raise
        name = info.get("name", "anfra")
        version = info.get("version", "unknown")
        return f"{name} {version}"

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke an MCP tool; returns the parsed inner JSON payload.

        Raises the typed AnfraError hierarchy for every failure shape seen
        from anfra 0.13.3 (see errors.py). Never retries query failures —
        they are deterministic.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        body = self._rpc(payload)
        result = body.get("result")
        if not isinstance(result, dict):
            err = body.get("error")
            if isinstance(err, dict):
                raise AnfraError(
                    f"MCP error {err.get('code')}: {err.get('message')}",
                    request_id=str(err.get("data", "")) or None,
                )
            raise AnfraContractError("tools/call response missing result{}")
        content = result.get("content")
        if not isinstance(content, list) or not content:
            raise AnfraContractError("tools/call result has no content[]")
        text = content[0].get("text") if isinstance(content[0], dict) else None
        if not isinstance(text, str):
            raise AnfraContractError("tools/call content[0].text missing or not a string")
        try:
            inner = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnfraContractError(
                f"tools/call content is not JSON: {text[:120]}",
                hint="If this started after an anfra upgrade, pin the anfra version.",
            ) from exc
        if isinstance(inner, dict) and isinstance(inner.get("error"), dict):
            raise self._map_query_error(inner["error"])
        return inner

    @staticmethod
    def _map_query_error(error: dict) -> AnfraQueryError:
        details = error.get("details") or {}
        request_id = error.get("request_id")
        if isinstance(details.get("diagnostics"), list):
            return AnfraCompileError.from_diagnostics(
                details["diagnostics"], request_id=request_id, payload=details
            )
        if isinstance(details.get("violations"), list):
            return AnfraValidationError.from_violations(
                details["violations"], request_id=request_id, payload=details
            )
        return AnfraQueryError(
            str(error.get("message", "query failed")),
            request_id=request_id,
            payload=details,
        )

    # -- query surface ------------------------------------------------------

    def query(
        self,
        *,
        dimensions: dict[str, str] | None = None,
        measures: dict[str, str] | None = None,
        filters: list[Filter | Condition] | None = None,
        order_by: list[tuple[str, str]] | None = None,
        dataset: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        timezone: str | None = None,
    ) -> QueryResult:
        """Explore by logical elements.

        dimensions/measures: ``{"alias": "model.field" | "metric_name"}``.
        order_by: ``[(alias, "asc"|"desc"), ...]`` rendered as AQL sorts.
        Structured :class:`Filter` items go in ``input.filters`` (server-validated);
        :class:`Condition` items go in ``input.conditions``.
        """
        return self.aql(
            self._render_explore(dimensions or {}, measures or {}, order_by or []),
            filters=filters,
            dataset=dataset,
            page=page,
            page_size=page_size,
            timezone=timezone,
        )

    @staticmethod
    def _render_explore(
        dimensions: dict[str, str], measures: dict[str, str], order_by: list[tuple[str, str]]
    ) -> str:
        if not dimensions and not measures:
            raise ValueError("query() needs at least one dimension or measure")
        lines = ["explore {"]
        if dimensions:
            lines.append("  dimensions {")
            lines += [f"    {alias}: {ref}" for alias, ref in dimensions.items()]
            lines.append("  }")
        if measures:
            lines.append("  measures {")
            lines += [f"    {alias}: {ref}" for alias, ref in measures.items()]
            lines.append("  }")
        if order_by:
            lines.append("  sorts {")
            lines += [f"    {alias} {direction}" for alias, direction in order_by]
            lines.append("  }")
        lines.append("}")
        return "\n".join(lines)

    def aql(
        self,
        query: str,
        *,
        filters: list[Filter | Condition] | None = None,
        dataset: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        timezone: str | None = None,
    ) -> QueryResult:
        """Run an AQL string (e.g. a query with query-local ``case()`` dimensions).

        Structured filters are ANDed server-side via ``input.filters``; free-form
        conditions via ``input.conditions``. Dynamic per-request filtering without
        string-interpolating the query text is the whole point.
        """
        ds = dataset or self.dataset
        if not ds:
            raise ValueError("no dataset given: pass dataset=... or set it on the client")
        arguments: dict = {"dataset": ds, "query": query}
        input_part: dict = {}
        structured = [f for f in (filters or []) if isinstance(f, Filter)]
        conditions = [f for f in (filters or []) if isinstance(f, Condition)]
        if structured:
            input_part["filters"] = [f.to_payload() for f in structured]
        if conditions:
            input_part["conditions"] = [c.to_payload() for c in conditions]
        if input_part:
            arguments["input"] = input_part
        if page is not None:
            arguments["page"] = page
        if page_size is not None:
            arguments["page_size"] = page_size
        if timezone:
            arguments["timezone"] = timezone
        return self._result_from(self.call_tool("core.query", arguments))

    def sql(self, query: str, *, data_source: str, **kw: object) -> QueryResult:
        """Raw SQL against a data source (utilities, health checks, edge cases)."""
        arguments = {"data_source": data_source, "lang": "sql", "query": query}
        arguments.update(kw)  # type: ignore[arg-type]
        return self._result_from(self.call_tool("core.query", arguments))

    def compile(self, query: str, *, dataset: str | None = None) -> str:
        """Compile AQL to SQL without executing (``core.query.compile``)."""
        ds = dataset or self.dataset
        if not ds:
            raise ValueError("no dataset given: pass dataset=... or set it on the client")
        inner = self.call_tool("core.query.compile", {"dataset": ds, "query": query})
        sql = inner.get("sql") if isinstance(inner, dict) else None
        if not isinstance(sql, str):
            raise AnfraContractError("core.query.compile response missing sql string")
        return sql

    @staticmethod
    def _timings_of(inner: dict) -> dict:
        timings = inner.get("timings")
        return timings if isinstance(timings, dict) else {}

    @staticmethod
    def _result_from(inner: dict) -> QueryResult:
        result = inner.get("result")
        if not isinstance(result, dict) or "fields" not in result or "records" not in result:
            raise AnfraContractError(
                "core.query response missing result.fields/records",
                hint="If this started after an anfra upgrade, the response envelope changed.",
            )
        columns = tuple(
            Column.from_raw(c) for c in (inner.get("columns") or []) if isinstance(c, dict)
        )
        return QueryResult(
            fields=[str(f) for f in result["fields"]],
            records=result["records"],
            columns=columns,
            sql=inner.get("sql") if isinstance(inner.get("sql"), str) else None,
            aql=inner.get("aql") if isinstance(inner.get("aql"), str) else None,
            has_more=bool(inner.get("has_more", False)),
            timings=AnfraClient._timings_of(inner),
        )
