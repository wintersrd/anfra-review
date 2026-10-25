"""Every AQL query embedded in apps/running.html must execute against the DB.

This is the agent's safety net for semantic-layer edits: extract the exact
AQL the browser will run and execute each block through the real anfra
engine. Skips (with reason) while `anfra serve` holds the DuckDB lock.
"""

from __future__ import annotations

import pytest
from anfra_utils import anfra, anfra_available, db_lock_held

pytestmark = pytest.mark.anfra


@pytest.mark.skipif(not anfra_available(), reason="~/.anfra/bin/anfra not installed")
def test_every_app_query_executes(repo_root, aql_blocks):
    if db_lock_held(repo_root):
        pytest.skip("anfra serve holds the DuckDB lock — stop the server to run anfra tests")
    failures = {}
    for qid, aql in sorted(aql_blocks.items()):
        result = anfra(["query", "--dataset", "running_analytics", aql], cwd=repo_root)
        if result.returncode != 0:
            failures[qid] = (result.stdout + result.stderr).strip()[:300]
    assert not failures, f"{len(failures)}/{len(aql_blocks)} app queries failed:\n" + "\n".join(
        f"  {qid}: {msg}" for qid, msg in failures.items()
    )


@pytest.mark.skipif(not anfra_available(), reason="~/.anfra/bin/anfra not installed")
def test_expected_query_count(repo_root, aql_blocks):
    # 21 queries as of the surface/stride round; bump deliberately on change
    assert len(aql_blocks) == 21
