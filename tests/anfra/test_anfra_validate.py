"""anfra repo health: AML validation must pass before anything else."""

from __future__ import annotations

import pytest
from anfra_utils import anfra, anfra_available

pytestmark = pytest.mark.anfra


@pytest.mark.skipif(not anfra_available(), reason="~/.anfra/bin/anfra not installed")
def test_validate_passes(repo_root):
    result = anfra(["validate"], cwd=repo_root)
    out = result.stdout + result.stderr
    assert result.returncode == 0, f"anfra validate failed:\n{out}"
    assert "valid: false" not in out, out
