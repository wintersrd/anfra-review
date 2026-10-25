"""anfra_client — Python consumer SDK for anfra's MCP server.

anfra acts as the infrastructure backend (database, semantic model, query
engine); this package is the thin, typed boundary data apps code against.
Domain-agnostic: the running-analytics app is consumer #1, the next data app
should need nothing here but its own dataset name and queries.
"""

from anfra_client.client import AnfraClient, QueryElem, QueryElems
from anfra_client.errors import (
    AnfraCompileError,
    AnfraConnectionError,
    AnfraContractError,
    AnfraError,
    AnfraQueryError,
    AnfraSessionError,
    AnfraValidationError,
)
from anfra_client.filters import between, condition, equals, is_in, last
from anfra_client.models import Column, Condition, Filter, QueryResult

__all__ = [
    "AnfraClient",
    "QueryElem",
    "QueryElems",
    "AnfraError",
    "AnfraConnectionError",
    "AnfraSessionError",
    "AnfraQueryError",
    "AnfraCompileError",
    "AnfraValidationError",
    "AnfraContractError",
    "Filter",
    "Condition",
    "Column",
    "QueryResult",
    "is_in",
    "equals",
    "between",
    "last",
    "condition",
]
