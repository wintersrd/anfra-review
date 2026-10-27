"""Fixtures shared by the anfra test modules."""

from __future__ import annotations

import pytest
from anfra_utils import extract_aql


@pytest.fixture(scope="module")
def aql_blocks(repo_root):
    html = (repo_root / "apps" / "running.html").read_text()
    blocks = extract_aql(html)
    assert blocks, "no createQuery AQL found in apps/running.html — regex drift?"
    return blocks


@pytest.fixture(scope="module")
def cycling_blocks(repo_root):
    html = (repo_root / "apps" / "cycling.html").read_text()
    blocks = extract_aql(html)
    assert blocks, "no createQuery AQL found in apps/cycling.html — regex drift?"
    return blocks
