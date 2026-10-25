"""Shared fixtures: repo paths, import paths, and a fixture DuckDB.

The fixture DB is built from the *committed* data/raw CSVs, so every test run
is deterministic and needs no network / API key / live re-sync.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))  # sync_intervals_icu
sys.path.insert(0, str(REPO / "streamlit_app"))  # queries, theme (flat imports)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture(scope="session")
def raw_dir() -> Path:
    return REPO / "data" / "raw"


@pytest.fixture(scope="session")
def fixture_db(raw_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """DuckDB built from the committed data/raw CSVs (no reader snapshot)."""
    import sync_intervals_icu as sync

    db = tmp_path_factory.mktemp("db") / "fixture.duckdb"
    sync.build_db(raw_dir=raw_dir, db_path=db, write_reader=False)
    return db


@pytest.fixture(scope="session")
def fixture_conn(fixture_db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(fixture_db), read_only=True)


@pytest.fixture(scope="session")
def queries_mod(fixture_conn: duckdb.DuckDBPyConnection):
    """The streamlit queries module wired to the fixture DB.

    Replaces ``queries.get_conn`` wholesale (bypassing the streamlit resource
    cache). All integration tests share one fixture DB, so the query-result
    caches stay consistent across tests.
    """
    import queries

    mp = pytest.MonkeyPatch()
    mp.setattr(queries, "get_conn", lambda: fixture_conn)
    yield queries
    mp.undo()
