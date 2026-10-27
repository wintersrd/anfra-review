"""Paste into tests/conftest.py (adapt names to your app).

Builds a fixture warehouse from committed data/raw via the repo's sync script
and points the ORACLE at it. The live layer is NOT pointed here — equivalence
tests compare oracle-on-fixture vs live-on-server, which is exactly the
property under test.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import duckdb
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
import sync_intervals_icu as sync  # noqa: E402


@pytest.fixture(scope="session")
def example_fixture_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db = tmp_path_factory.mktemp("example_db") / "example.duckdb"
    sync.build_db(raw_dir=REPO / "data" / "raw", db_path=db, write_reader=False)
    return db


@pytest.fixture(scope="session")
def example_fixture_conn(example_fixture_db: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect(str(example_fixture_db), read_only=True)
    yield conn
    conn.close()


@pytest.fixture
def example_oracle(
    example_fixture_conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> ModuleType:
    import example_data_oracle as oracle

    monkeypatch.setattr(oracle, "get_conn", lambda: example_fixture_conn)
    return oracle
