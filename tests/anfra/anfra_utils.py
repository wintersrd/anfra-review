"""Shared helpers for the anfra test layer."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ANFRA_BIN = Path.home() / ".anfra" / "bin" / "anfra"
LOCK_SENTINEL = "initialize driver"


def anfra_available() -> bool:
    return ANFRA_BIN.exists()


def anfra(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(ANFRA_BIN), *args], cwd=cwd, capture_output=True, text=True, timeout=120
    )


def db_lock_held(repo: Path) -> bool:
    """True when `anfra serve` holds the DuckDB write lock (queries fail)."""
    if not anfra_available():
        return True
    probe = anfra(
        ["query", "--dataset", "running_analytics", "explore { measures { x: total_activities } }"],
        cwd=repo,
    )
    return LOCK_SENTINEL in (probe.stdout + probe.stderr)


def extract_aql(html: str) -> dict[str, str]:
    """Pull every createQuery AQL block out of an anfra app HTML file."""
    pattern = re.compile(r"createQuery\('([^']+)',\s*\{.*?aql:\s*`(.*?)`\s*,?\s*\}\)", re.DOTALL)
    return {qid: aql.strip() for qid, aql in pattern.findall(html)}
