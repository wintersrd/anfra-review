"""ECharts SSR render harness for apps/cycling.html.

Companion to test_chart_render.py (running app): runs every cycling app
query through the real anfra engine, feeds the results to chart_harness.mjs
(node + echarts in SSR mode), and fails if any chart's setOption throws.
Skips while `anfra serve` holds the DuckDB lock, when node is missing, or
when the pinned echarts bundle can't be fetched (cached in tests/anfra/.cache,
git-ignored).
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from anfra_utils import anfra, anfra_available, db_lock_held
from test_chart_render import _echarts_bundle

pytestmark = [pytest.mark.anfra, pytest.mark.charts]


@pytest.fixture(scope="module")
def harness_ready(repo_root):
    if not anfra_available():
        pytest.skip("~/.anfra/bin/anfra not installed")
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    bundle = _echarts_bundle(repo_root)
    if bundle is None:
        pytest.skip("could not fetch echarts 6.1.0 (offline?)")
    if db_lock_held(repo_root):
        pytest.skip("anfra serve holds the DuckDB lock — stop the server to run anfra tests")
    return bundle


def _parse_yaml_records_nullable(out: str) -> tuple[list[str], list[list]]:
    """Like test_chart_render._parse_yaml_records but keeps YAML nulls as None.

    The cycling app renders rows that legitimately contain nulls (long rides
    without decoupling); turning them into the string "null" would poison the
    JS `num()` helper with NaN and mask or fake render failures.
    """
    lines = out.splitlines()
    try:
        i = lines.index("    fields:")
    except ValueError:
        raise AssertionError("no result.fields in anfra query output") from None
    j = next(k for k, ln in enumerate(lines) if ln.strip() == "records:")
    fields = [ln.strip()[2:] for ln in lines[i + 1 : j] if ln.strip().startswith("- ")]
    records: list[list] = []
    for ln in lines[j + 1 :]:
        s = ln.strip()
        if s.startswith("- - "):
            records.append([_scalar_nullable(s[4:])])
        elif s.startswith("- ") and records:
            records[-1].append(_scalar_nullable(s[2:]))
        elif s == "sql: |-" or s.startswith("sql:"):
            break
    return fields, records


def _scalar_nullable(token: str):
    token = token.strip().strip('"')
    if token in {"null", "~", ""}:
        return None
    try:
        return float(token)
    except ValueError:
        return token


def test_every_cycling_chart_renders_in_ssr(repo_root, cycling_blocks, harness_ready, tmp_path):
    results = {}
    for qid, aql in sorted(cycling_blocks.items()):
        out = anfra(["query", "--dataset", "running_analytics", aql], cwd=repo_root)
        if out.returncode != 0:
            raise AssertionError(f"query {qid} failed: {(out.stdout + out.stderr)[:300]}")
        fields, records = _parse_yaml_records_nullable(out.stdout)
        # the app reads row values as object properties (r.week, r.ride_km, ...)
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
            str(repo_root / "apps" / "cycling.html"),
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
