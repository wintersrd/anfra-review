"""Every AQL query embedded in apps/cycling.html must execute against the DB.

Companion to test_anfra_queries.py (running app): same safety net for the
cycling dashboard's semantic layer. Skips (with reason) while `anfra serve`
holds the DuckDB lock.
"""

from __future__ import annotations

import pytest
from anfra_utils import anfra, anfra_available, db_lock_held

pytestmark = pytest.mark.anfra


@pytest.mark.skipif(not anfra_available(), reason="~/.anfra/bin/anfra not installed")
def test_every_cycling_app_query_executes(repo_root, cycling_blocks):
    if db_lock_held(repo_root):
        pytest.skip("anfra serve holds the DuckDB lock — stop the server to run anfra tests")
    failures = {}
    for qid, aql in sorted(cycling_blocks.items()):
        result = anfra(["query", "--dataset", "running_analytics", aql], cwd=repo_root)
        if result.returncode != 0:
            failures[qid] = (result.stdout + result.stderr).strip()[:300]
    assert not failures, (
        f"{len(failures)}/{len(cycling_blocks)} cycling app queries failed:\n"
        + "\n".join(f"  {qid}: {msg}" for qid, msg in failures.items())
    )


@pytest.mark.skipif(not anfra_available(), reason="~/.anfra/bin/anfra not installed")
def test_expected_cycling_query_count(cycling_blocks):
    # 22 queries as of the first cycling dashboard build; bump deliberately on change
    assert len(cycling_blocks) == 22
