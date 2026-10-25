"""ECharts SSR render harness for apps/running.html.

Runs every app query through the real anfra engine, feeds the results to
chart_harness.mjs (node + echarts in SSR mode), and fails if any chart's
setOption throws. Skips while `anfra serve` holds the DuckDB lock, when node
is missing, or when the pinned echarts bundle can't be fetched (cached in
tests/anfra/.cache, git-ignored).
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from anfra_utils import anfra, anfra_available, db_lock_held

pytestmark = [pytest.mark.anfra, pytest.mark.charts]

ECHARTS_VERSION = "6.1.0"  # keep in sync with the CDN tag in apps/running.html
ECHARTS_URL = f"https://cdn.jsdelivr.net/npm/echarts@{ECHARTS_VERSION}/dist/echarts.min.js"


def _echarts_bundle(repo_root) -> str | None:
    cache = repo_root / "tests" / "anfra" / ".cache" / "echarts.min.js"
    if cache.exists() and cache.stat().st_size > 500_000:
        return str(cache)
    if shutil.which("curl") is None:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    fetch = subprocess.run(
        ["curl", "-fsSL", "-o", str(cache), ECHARTS_URL],
        capture_output=True,
        timeout=60,
    )
    if fetch.returncode != 0 or not cache.exists() or cache.stat().st_size < 500_000:
        return None
    return str(cache)


@pytest.fixture(scope="module")
def harness_ready(repo_root):
    if not anfra_available():
        pytest.skip("~/.anfra/bin/anfra not installed")
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    bundle = _echarts_bundle(repo_root)
    if bundle is None:
        pytest.skip(f"could not fetch echarts {ECHARTS_VERSION} (offline?)")
    if db_lock_held(repo_root):
        pytest.skip("anfra serve holds the DuckDB lock — stop the server to run anfra tests")
    return bundle


def _run_query_rows(repo_root, aql: str):
    result = anfra(["query", "--dataset", "running_analytics", aql], cwd=repo_root)
    if result.returncode != 0:
        raise AssertionError(f"query failed: {(result.stdout + result.stderr)[:300]}")
    return _parse_yaml_records(result.stdout)


def _parse_yaml_records(out: str) -> tuple[list[str], list[list]]:
    """Pull result.fields / result.records from anfra query YAML output."""
    lines = out.splitlines()
    try:
        i = lines.index("    fields:")
    except ValueError:
        raise AssertionError("no result.fields in anfra query output") from None
    j = next(k for k, ln in enumerate(lines) if ln.strip() == "records:")
    fields = [ln.strip()[2:] for ln in lines[i + 1 : j] if ln.strip().startswith("- ")]
    records = []
    for ln in lines[j + 1 :]:
        s = ln.strip()
        if s.startswith("- - "):
            records.append([_scalar(s[4:])])
        elif s.startswith("- ") and records:
            records[-1].append(_scalar(s[2:]))
        elif s == "sql: |-" or s.startswith("sql:"):
            break
    return fields, records


def _scalar(token: str):
    token = token.strip().strip('"')
    try:
        return float(token)
    except ValueError:
        return token


def test_every_chart_renders_in_ssr(repo_root, aql_blocks, harness_ready, tmp_path):
    results = {}
    for qid, aql in sorted(aql_blocks.items()):
        fields, records = _run_query_rows(repo_root, aql)
        # the app reads row values as object properties (r.day, r.run_km, ...)
        # — real anfra rows are objects keyed by fieldName
        results[qid] = {
            "fields": fields,
            "rows": [dict(zip(fields, rec, strict=True)) for rec in records],
        }

    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps(results))

    proc = subprocess.run(
        [
            "node",
            str(repo_root / "tests" / "anfra" / "chart_harness.mjs"),
            str(results_file),
            str(repo_root / "apps" / "running.html"),
            harness_ready,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"chart harness found render failures:\n{output}"
    assert "THROW" not in output, output
    assert "charts attempted:" in output
