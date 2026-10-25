"""Exception hierarchy for the anfra MCP client.

Every error carries an optional ``hint`` — an actionable next step for the app
developer or end user — and, where the server provided one, the ``request_id``
for log correlation.
"""

from __future__ import annotations


class AnfraError(Exception):
    """Base class for every error raised by :mod:`anfra_client`."""

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        request_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.request_id = request_id
        self.payload = payload or {}

    def __str__(self) -> str:  # noqa: D105
        parts = [self.message]
        if self.hint:
            parts.append(f"hint: {self.hint}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " | ".join(parts)


class AnfraConnectionError(AnfraError):
    """The anfra server could not be reached, or answered with a transport-level failure.

    Raised for DNS/socket failures, timeouts, and HTTP 4xx/5xx responses that
    are not session-related. If you see this repeatedly, the ``anfra serve``
    process is probably down.
    """


class AnfraSessionError(AnfraError):
    """The MCP session was rejected (expired or unknown).

    The client normally recovers from this transparently by re-running the
    MCP handshake once. If it escapes, the server is repeatedly dropping
    sessions (restart loop?) — check the server process.
    """


class AnfraQueryError(AnfraError):
    """The server accepted the request but the query failed."""


class AnfraCompileError(AnfraQueryError):
    """AQL compilation failed (unknown model/field/metric, syntax error, ...).

    ``diagnostics`` holds the server's list of ``{message, severity, line,
    column}`` entries — render them in-app for a good editing experience.
    """

    def __init__(self, message: str, *, diagnostics: list[dict], **kw: object) -> None:
        super().__init__(message, **kw)  # type: ignore[arg-type]
        self.diagnostics = diagnostics

    @classmethod
    def from_diagnostics(cls, diagnostics: list[dict], **kw: object) -> AnfraCompileError:
        first = diagnostics[0] if diagnostics else {}
        msg = first.get("message", "AQL compilation failed").strip()
        line, col = first.get("line"), first.get("column")
        if line is not None:
            msg = (
                f"{msg} (line {line}, column {col})" if col is not None else f"{msg} (line {line})"
            )
        return cls(msg, diagnostics=diagnostics, **kw)  # type: ignore[arg-type]


class AnfraValidationError(AnfraQueryError):
    """The request input was rejected (unknown field, bad operator arity, ...).

    ``violations`` holds the server's list of ``{field, code, message}``
    entries; ``field`` is a path like ``input.filters[0].field``.
    """

    def __init__(self, message: str, *, violations: list[dict], **kw: object) -> None:
        super().__init__(message, **kw)  # type: ignore[arg-type]
        self.violations = violations

    @classmethod
    def from_violations(cls, violations: list[dict], **kw: object) -> AnfraValidationError:
        msgs = [f"{v.get('field', '?')}: {v.get('message', 'invalid')}" for v in violations]
        return cls("; ".join(msgs) or "invalid request", violations=violations, **kw)  # type: ignore[arg-type]


class AnfraContractError(AnfraError):
    """The server response did not match the contract the client expects.

    This is the client's regression tripwire: it fires when anfra changes its
    MCP response envelope (missing fields, non-JSON content, unmatched
    JSON-RPC ids). Pin the anfra version when this starts appearing.
    """
