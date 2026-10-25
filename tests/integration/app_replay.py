"""Record/replay MCP responses for the full-app smoke test.

Record (needs `anfra serve` up, data/ snapshot current):

    uv run python tests/integration/app_replay.py

This runs every function in ``streamlit_app.queries_aql`` once against the
live server and stores each raw MCP response under ``replay_data/`` (committed).
The smoke test then replays them offline: no server, deterministic charts.

The recordings double as a contract regression net — if anfra's response
envelope (SSE framing, columns/records shape) drifts, replay breaks loudly.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "streamlit_app"))

from anfra_client import AnfraClient  # noqa: E402
from anfra_client.transport import TransportResponse, UrllibTransport  # noqa: E402

REPLAY_DIR = Path(__file__).resolve().parent / "replay_data"


def _key_for(arguments: dict) -> str:
    raw = json.dumps(arguments, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


class RecordingTransport:
    """Pass-through transport that stores every response by arguments hash."""

    def __init__(self, inner: UrllibTransport) -> None:
        self.inner = inner
        REPLAY_DIR.mkdir(parents=True, exist_ok=True)

    def post(self, payload: dict, session_id: str | None) -> TransportResponse:
        resp = self.inner.post(payload, session_id)
        if payload.get("method") == "tools/call":
            arguments = payload.get("params", {}).get("arguments", {})
            key = _key_for(arguments)
            tool = payload.get("params", {}).get("name", "unknown")
            (REPLAY_DIR / f"{tool}__{key}.json").write_text(
                json.dumps(
                    {
                        "tool": tool,
                        "key": key,
                        "arguments": arguments,
                        "status": resp.status,
                        "body": resp.text,
                    },
                    indent=1,
                )
            )
        return resp


def record() -> int:
    """Run every queries_aql function once; write responses to replay_data/."""
    warnings.filterwarnings("ignore")
    import queries_aql as q  # noqa: E402  (flat import, like the app)

    base = AnfraClient.from_env(dataset=q.DATASET)
    client = AnfraClient(
        url=base.url,
        dataset=q.DATASET,
        transport=RecordingTransport(UrllibTransport(base.url, timeout=30.0)),
    )
    q.get_client = lambda: client  # type: ignore[method-assign]

    fns = [
        q.kpi_fitness,
        lambda: q.kpi_week_distance((), ()),
        lambda: q.kpi_90d(()),
        q.kpi_decoupling,
        q.date_bounds,
    ]
    # The app's default preset is "Last 90 days" derived from date_bounds();
    # recordings must use the exact same arguments or replay misses.
    lo, hi = q.date_bounds()
    win = ((hi - dt.timedelta(days=89)).isoformat(), hi.isoformat())
    fns += [
        lambda: q.fitness_trend(*win),
        lambda: q.load_ramp(*win),
        lambda: q.weekly_run_distance(*win, (), ()),
        lambda: q.daily_runs(*win, (), ()),
        lambda: q.sport_mix(*win),
        lambda: q.weekly_category(*win),
        lambda: q.monthly_pace(*win, (), ()),
        lambda: q.monthly_cadence(*win, (), ()),
        lambda: q.monthly_efficiency(*win, (), ()),
        lambda: q.surface_pace_trend(*win, (), ()),
        lambda: q.stride_trend(*win, (), ()),
        lambda: q.hilliness_trend(*win, (), ()),
        lambda: q.decoupling_by_surface(*win),
        lambda: q.stride_vs_pace(*win, (), ()),
        lambda: q.pace_blocks_weekly(*win, (), ()),
        lambda: q.decoupling_trend(*win),
        lambda: q.pace_by_temp(*win, (), ()),
    ]
    # exercise sport/surface filter variants too (same queries + input.filters)
    fns += [
        lambda: q.kpi_week_distance(("run",), ("road",)),
        lambda: q.kpi_90d(("run",)),
        lambda: q.surface_pace_trend(*win, (), ("road",)),
    ]
    for fn in fns:
        fn()
    n = len(list(REPLAY_DIR.glob("*.json")))
    print(f"recorded {n} responses into {REPLAY_DIR}")
    return n


def replay_client() -> AnfraClient | None:
    """AnfraClient answering from recorded responses, or None if none recorded."""
    from anfra_client.mock import MockTransport  # noqa: E402

    recordings = sorted(REPLAY_DIR.glob("*.json"))
    if not recordings:
        return None
    bodies: dict[str, dict] = {}
    for f in recordings:
        rec = json.loads(f.read_text())
        bodies[rec["key"]] = rec

    mt = MockTransport()

    def match(payload: dict) -> bool:
        return payload.get("method") == "tools/call"

    def respond(payload: dict) -> TransportResponse:
        arguments = payload.get("params", {}).get("arguments", {})
        rec = bodies.get(_key_for(arguments))
        if rec is None:
            return TransportResponse(500, {}, "")
        return TransportResponse(rec["status"], {}, rec["body"])

    mt.on(match, respond)
    return AnfraClient(transport=mt, dataset="running_analytics")


if __name__ == "__main__":
    record()
