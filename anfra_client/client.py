"""AnfraClient — a small, abstracted Python consumer of anfra's MCP server.

anfra (``anfra serve``) is the infrastructure backend: database, semantic
model (AML), and query engine. This client lets a Python data app express
logical query elements — dimensions, measures, filters — and get rows back,
without writing SQL or managing the DuckDB file.

Quickstart::

    from anfra_client import AnfraClient, is_in, between, last

    cx = AnfraClient.from_env(dataset="running_analytics")

    result = cx.query(
        dimensions=["activities.sport_group"],
        measures=["total_time_h"],
        filters=[is_in("activities.sport_group", ["run", "trail"])],
        order_by=["total_time_h desc"],
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
import re
import threading
import time
from collections.abc import Mapping, Sequence
from typing import cast

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

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")

# Logical query elements: "model.field" / "metric", ("alias", "model.field"),
# a sequence of either, or an {alias: ref} mapping.
QueryElem = str | tuple[str, str]
QueryElems = QueryElem | Sequence[QueryElem] | Mapping[str, str]


def _ident_or_fail(name: str, what: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(
            f"{what} {name!r} must be a valid AQL identifier "
            "(letters, digits, underscores; must not start with a digit)"
        )
    return name


def _alias_of(ref: str) -> str:
    """Default alias for a ref: the last path segment (``a.b.c`` -> ``c``)."""
    return ref.split(".")[-1].strip()


def _normalize_elems(value: QueryElems | None, kind: str) -> list[tuple[str, str]]:
    """Normalize the accepted element shapes into (alias, ref) pairs."""
    if value is None:
        return []
    if isinstance(value, Mapping):
        items: list[QueryElem] = list(value.items())
    elif isinstance(value, str) or (
        isinstance(value, tuple) and len(value) == 2 and all(isinstance(p, str) for p in value)
    ):
        items = [cast("QueryElem", value)]
    else:
        items = list(value)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            ref = item.strip()
            if not ref:
                raise ValueError(f"{kind}: empty element")
            alias = _alias_of(ref)
        else:
            alias, ref = item[0].strip(), item[1].strip()
            if not ref:
                raise ValueError(f"{kind}: empty ref for alias {alias!r}")
        _ident_or_fail(alias, f"{kind} alias")
        if alias in seen:
            raise ValueError(
                f"{kind}: duplicate alias {alias!r} — pass an explicit alias for one of them"
            )
        seen.add(alias)
        out.append((alias, ref))
    return out


def _render_preludes(
    custom_metrics: Mapping[str, str] | None,
    custom_dimensions: Mapping[str, str] | None = None,
) -> list[str]:
    lines: list[str] = []
    for name, expr in (custom_metrics or {}).items():
        _ident_or_fail(name, "custom metric name")
        lines.append(f"metric {name} = {expr};")
    for name, expr in (custom_dimensions or {}).items():
        if not _FIELD_RE.match(name):
            raise ValueError(
                f"custom dimension name {name!r} must be a dotted model.field path "
                "(e.g. 'activities.pace_bucket')"
            )
        lines.append(f"dimension {name} = {expr};")
    return lines


def _normalize_sorts(order_by: Sequence[str | tuple[str, str]] | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in order_by or ():
        if isinstance(item, str):
            parts = item.split()
            if len(parts) == 1:
                alias, direction = parts[0], "asc"
            elif len(parts) == 2:
                alias, direction = parts
            else:
                raise ValueError(f"order_by {item!r}: expected 'alias' or 'alias asc|desc'")
        else:
            alias, direction = item
        direction = direction.lower()
        if direction not in ("asc", "desc"):
            raise ValueError(f"order_by {item!r}: direction must be 'asc' or 'desc'")
        _ident_or_fail(alias, "order_by alias")
        out.append((alias, direction))
    return out


def _split_filters(
    filters: Sequence[Filter | Condition | str] | None,
) -> tuple[list[Filter], list[Condition]]:
    """Route mixed filter items: Filter -> input.filters, Condition/str -> conditions."""
    structured: list[Filter] = []
    conditions: list[Condition] = []
    for item in filters or ():
        if isinstance(item, Filter):
            structured.append(item)
        elif isinstance(item, Condition):
            conditions.append(item)
        elif isinstance(item, str):
            conditions.append(Condition(expr=item))
        else:
            raise TypeError(
                f"filters: expected Filter, Condition, or str, got {type(item).__name__}"
            )
    return structured, conditions


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
        dimensions: QueryElems | None = None,
        measures: QueryElems | None = None,
        custom_metrics: Mapping[str, str] | None = None,
        custom_dimensions: Mapping[str, str] | None = None,
        filters: Sequence[Filter | Condition | str] | None = None,
        order_by: Sequence[str | tuple[str, str]] | None = None,
        dataset: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        timezone: str | None = None,
        *,
        is_explore: bool = True,
    ) -> QueryResult:
        """Run an explore query built from logical elements — the default surface.

        Every element accepts short or explicit forms:

        - ``dimensions``/``measures``: ``"activities.sport_group"`` (alias
          derived from the last path segment), ``("sport", "activities.sport_group")``
          (explicit alias), a list of either, or the original
          ``{"sport": "activities.sport_group"}`` mapping. Explicit aliases are
          always rendered so result columns have clean, predictable names.
        - ``custom_metrics``: ``{"name": "expr"}`` rendered as query-local
          ``metric name = expr;`` assignments. Reference them from ``measures``
          by bare name.
        - ``custom_dimensions``: ``{"model.field": "expr"}`` rendered as
          query-local ``dimension model.field = expr;`` assignments (case
          buckets, derived values). Reference them from ``dimensions`` by the
          full dotted path.
        - ``filters``: :class:`Filter` (server-validated ``input.filters``),
          :class:`Condition` or plain ``str`` (free-form ``input.conditions``),
          freely mixed.
        - ``order_by``: ``"hours desc"`` (direction optional, default asc) or
          ``(alias, direction)`` tuples.
        - ``is_explore=False`` renders only the ``custom_metrics`` assignments —
          no rows come back; useful to inspect generated SQL via
          :meth:`compile`-style flows. Requires ``custom_metrics``.

        Example::

            res = cx.query(
                custom_metrics={
                    "this_week_run_km": (
                        "run_distance_km | where(activities.week_start"
                        " == max(activities.week_start))"
                    )
                },
                measures=[("this_week", "this_week_run_km")],
                filters=["activities.week_start matches @(last 4 weeks)"],
                timezone="Europe/Paris",
            )
            df = res.frame()
        """
        query = self._render_query(
            dimensions=dimensions,
            measures=measures,
            custom_metrics=custom_metrics,
            custom_dimensions=custom_dimensions,
            order_by=order_by,
            is_explore=is_explore,
        )
        return self.aql(
            query,
            filters=filters,  # type: ignore[arg-type]
            dataset=dataset,
            page=page,
            page_size=page_size,
            timezone=timezone,
        )

    @staticmethod
    def _render_query(
        dimensions: QueryElems | None,
        measures: QueryElems | None,
        custom_metrics: Mapping[str, str] | None,
        custom_dimensions: Mapping[str, str] | None,
        order_by: Sequence[str | tuple[str, str]] | None,
        is_explore: bool,
    ) -> str:
        preludes = _render_preludes(custom_metrics, custom_dimensions)
        if not is_explore:
            if not preludes:
                raise ValueError(
                    "query(is_explore=False) renders only custom_metrics assignments; "
                    "pass custom_metrics=... (or use is_explore=True)"
                )
            return "\n".join(preludes)
        dims = _normalize_elems(dimensions, "dimensions")
        meas = _normalize_elems(measures, "measures")
        if not dims and not meas:
            raise ValueError(
                "query() needs at least one dimension or measure "
                "(or custom_metrics with is_explore=False)"
            )
        lines = preludes + ["explore {"]
        if dims:
            lines.append("  dimensions {")
            lines += [f"    {alias}: {ref}," for alias, ref in dims[:-1]]
            lines.append(f"    {dims[-1][0]}: {dims[-1][1]}")
            lines.append("  }")
        if meas:
            lines.append("  measures {")
            lines += [f"    {alias}: {ref}," for alias, ref in meas[:-1]]
            lines.append(f"    {meas[-1][0]}: {meas[-1][1]}")
            lines.append("  }")
        sorts = _normalize_sorts(order_by)
        if sorts:
            lines.append("  sorts {")
            lines += [f"    {alias} {direction}," for alias, direction in sorts[:-1]]
            lines.append(f"    {sorts[-1][0]} {sorts[-1][1]}")
            lines.append("  }")
        lines.append("}")
        return "\n".join(lines)

    @staticmethod
    def _render_explore(
        dimensions: dict[str, str], measures: dict[str, str], order_by: list[tuple[str, str]]
    ) -> str:
        """Legacy dict-only renderer (kept for compatibility with older callers)."""
        return AnfraClient._render_query(dimensions, measures, None, None, order_by, True)

    def aql(
        self,
        query: str,
        *,
        filters: Sequence[Filter | Condition | str] | None = None,
        dataset: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        timezone: str | None = None,
    ) -> QueryResult:
        """Run an AQL string (e.g. a query with query-local ``case()`` dimensions).

        The escape hatch for shapes :meth:`query` cannot express. Structured
        filters are ANDed server-side via ``input.filters``; free-form
        conditions (or plain strings) via ``input.conditions``. Dynamic
        per-request filtering without string-interpolating the query text is
        the whole point.
        """
        ds = dataset or self.dataset
        if not ds:
            raise ValueError("no dataset given: pass dataset=... or set it on the client")
        arguments: dict = {"dataset": ds, "query": query}
        structured, conditions = _split_filters(filters)
        input_part: dict = {}
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
