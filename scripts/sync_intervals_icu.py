#!/usr/bin/env python3
"""Sync intervals.icu activity history into a local DuckDB file.

Pulls the FULL activity history (a decade+) via the direct intervals.icu API,
plus weekly athlete summaries and (optionally) HR-decoupling computed from
streams for long runs. Everything lands in data/raw/*, then the `duckdb` CLI
builds data/running.duckdb from CSV extracts. Re-running rebuilds the DB.

Usage:
  python3 scripts/sync_intervals_icu.py [--since 2006-01-01]
      [--decoupling-since 2025-01-01] [--min-long-run-seconds 4500]
      [--skip-decoupling] [--skip-db]

Credentials: reads .env at the repo root (never printed):
  INTERVALS_ICU_API_KEY=...
  INTERVALS_ICU_ATHLETE_ID=8175042
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "running.duckdb"
BASE_URL = os.getenv("INTERVALS_API_BASE_URL", "https://intervals.icu/api/v1")

# ---------------------------------------------------------------------------
# sport grouping (v2-ready: run view today, cycling + strength later)
# ---------------------------------------------------------------------------
SPORT_GROUP = {
    "Run": "run", "TrailRun": "run", "VirtualRun": "run", "Treadmill": "run",
    "Ride": "ride", "VirtualRide": "ride", "MountainBikeRide": "ride",
    "GravelRide": "ride", "EBikeRide": "ride",
    "WeightTraining": "strength", "Workout": "strength",
    "Walk": "walk", "Hike": "walk",
    "Yoga": "yoga",
    "Rowing": "row", "VirtualRow": "row",
}

ACTIVITY_COLUMNS = [
    ("id", "VARCHAR"), ("name", "VARCHAR"), ("start_local", "TIMESTAMP"),
    ("start_utc", "TIMESTAMP"), ("type", "VARCHAR"), ("sub_type", "VARCHAR"),
    ("sport_group", "VARCHAR"), ("moving_time_s", "INTEGER"),
    ("elapsed_time_s", "INTEGER"), ("distance_m", "DOUBLE"),
    ("elev_gain_m", "DOUBLE"), ("elev_loss_m", "DOUBLE"),
    ("avg_speed_ms", "DOUBLE"), ("max_speed_ms", "DOUBLE"),
    ("avg_hr", "DOUBLE"), ("max_hr", "DOUBLE"), ("avg_cadence", "DOUBLE"),
    ("calories", "INTEGER"), ("avg_temp_c", "DOUBLE"),
    ("training_load", "DOUBLE"), ("atl", "DOUBLE"), ("ctl", "DOUBLE"),
    ("is_race", "BOOLEAN"), ("is_commute", "BOOLEAN"), ("trainer", "BOOLEAN"),
    ("device_name", "VARCHAR"), ("threshold_pace_ms", "DOUBLE"),
    ("decoupling", "DOUBLE"), ("gap_s", "INTEGER"),
    ("weighted_avg_watts", "DOUBLE"), ("icu_joules", "DOUBLE"),
    ("external_id", "VARCHAR"),
]

WEEKLY_COLUMNS = [
    ("week_start", "DATE"), ("activities", "INTEGER"), ("time_s", "INTEGER"),
    ("distance_m", "DOUBLE"), ("elev_gain_m", "DOUBLE"),
    ("training_load", "DOUBLE"), ("fitness", "DOUBLE"), ("fatigue", "DOUBLE"),
    ("form", "DOUBLE"), ("ramp_rate", "DOUBLE"), ("avg_weight_kg", "DOUBLE"),
    ("time_in_zones", "VARCHAR"),
]

BYCATEGORY_COLUMNS = [
    ("week_start", "DATE"), ("category", "VARCHAR"), ("activities", "INTEGER"),
    ("time_s", "INTEGER"), ("distance_m", "DOUBLE"), ("training_load", "DOUBLE"),
]

DECOUPLING_COLUMNS = [
    ("activity_id", "VARCHAR"), ("activity_start", "TIMESTAMP"),
    ("name", "VARCHAR"), ("decoupling_pct", "DOUBLE"), ("minutes", "DOUBLE"),
]


def load_env() -> dict:
    env: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("INTERVALS")})
    return env


def clean_text(value) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ord(ch) >= 32 or ch in "\t").strip()


def parse_ts(value) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        return ""


class Api:
    def __init__(self, api_key: str):
        self.token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
        self.calls = 0

    def get(self, path: str, params: dict | None = None):
        url = f"{BASE_URL}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        req.add_header("Authorization", "Basic " + self.token)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "running-analytics-sync/1.0 (personal dashboard)")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    self.calls += 1
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as err:
                if err.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(f"unreachable: {url}")


def fnum(obj: dict, *keys, default=None):
    """First present numeric key, tolerating string numbers."""
    for key in keys:
        value = obj.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def activity_row(act: dict) -> dict:
    atype = clean_text(act.get("type") or act.get("subtype"))
    start_utc = parse_ts(act.get("start_date"))
    return {
        "id": act.get("id"),
        "name": clean_text(act.get("name")),
        "start_local": parse_ts(act.get("start_date_local") or act.get("start_date")),
        "start_utc": start_utc,
        "type": atype,
        "sub_type": clean_text(act.get("subtype")),
        "sport_group": SPORT_GROUP.get(atype, "other"),
        "moving_time_s": int(fnum(act, "moving_time", "movingTime", default=0)),
        "elapsed_time_s": int(fnum(act, "elapsed_time", "elapsedTime", default=0)),
        "distance_m": fnum(act, "distance"),
        "elev_gain_m": fnum(act, "total_elevation_gain", "totalElevationGain"),
        "elev_loss_m": fnum(act, "total_elevation_loss", "totalElevationLoss"),
        "avg_speed_ms": fnum(act, "average_speed", "avg_speed"),
        "max_speed_ms": fnum(act, "max_speed"),
        "avg_hr": fnum(act, "average_heartrate", "average_hr", "avg_hr"),
        "max_hr": fnum(act, "max_heartrate", "max_hr"),
        "avg_cadence": fnum(act, "average_cadence", "avg_cad", "cad"),
        "calories": int(fnum(act, "calories", "kilojoules", default=0)),
        "avg_temp_c": fnum(act, "average_temp", "avg_temp"),
        "training_load": fnum(act, "icu_training_load", "training_load", "load"),
        "atl": fnum(act, "icu_atl", "atl"),
        "ctl": fnum(act, "icu_ctl", "ctl"),
        "is_race": bool(act.get("race")),
        "is_commute": bool(act.get("commute")),
        "trainer": bool(act.get("trainer")),
        "device_name": clean_text(act.get("device_name")),
        "threshold_pace_ms": fnum(act, "threshold_pace"),
        "decoupling": fnum(act, "decoupling"),
        "gap_s": int(fnum(act, "gap", default=0)),
        "weighted_avg_watts": fnum(
            act, "icu_weighted_avg_watts", "weighted_average_watts", "avg_watts"
        ),
        "icu_joules": fnum(act, "icu_joules"),
        "external_id": clean_text(act.get("external_id")),
    }


def sync_activities(api: Api, athlete_id: str, since: date, max_pages: int) -> list[dict]:
    """Walk /activities backward from today to `since`, deduping by id."""
    seen: dict[int, dict] = {}
    cursor = date.today()
    floor = since.isoformat()
    stall_guard = 0
    for page_no in range(1, max_pages + 1):
        page = api.get(
            f"/athlete/{athlete_id}/activities",
            {"oldest": floor, "newest": cursor.isoformat(), "limit": 200},
        )
        items = page if isinstance(page, list) else page.get("activities", [])
        new_ids = [a for a in items if a.get("id") not in seen]
        for act in new_ids:
            seen[act["id"]] = act
        oldest_start = None
        for act in items:
            ts = parse_ts(act.get("start_date") or act.get("start_date_local"))
            if ts:
                candidate = datetime.strptime(ts[:10], "%Y-%m-%d").date()
                oldest_start = candidate if oldest_start is None else min(oldest_start, candidate)
        print(
            f"  page {page_no}: +{len(new_ids)} new (total {len(seen)}), "
            f"window ends {oldest_start or 'n/a'}",
            flush=True,
        )
        if not items:
            break
        if oldest_start is None or oldest_start <= since:
            break
        if oldest_start >= cursor:
            # server ignored the cursor; force a manual 30-day step back
            stall_guard += 1
            if stall_guard > 3:
                print("  cursor stalled; stopping pagination", flush=True)
                break
            cursor = cursor - timedelta(days=30)
        else:
            stall_guard = 0
            cursor = oldest_start
        time.sleep(0.4)
    return sorted(seen.values(), key=lambda a: str(a.get("start_date") or ""))


def sync_weekly(api: Api, athlete_id: str, since: date) -> tuple[list[dict], list[dict]]:
    rows: dict[str, dict] = {}
    by_category: list[dict] = []
    year = since.year
    while year <= date.today().year:
        start = max(date(year, 1, 1), since)
        end = min(date(year, 12, 31), date.today())
        data = api.get(
            f"/athlete/{athlete_id}/athlete-summary",
            {"start": start.isoformat(), "end": end.isoformat()},
        )
        weeks = data if isinstance(data, list) else data.get("weeks", [])
        for week in weeks:
            ws = clean_text(
                week.get("week_start") or week.get("date") or week.get("weekStart")
            )[:10]
            if not ws or ws in rows:
                continue
            time_s = int(fnum(week, "time", "moving_time", default=0))
            distance_m = fnum(week, "distance") or 0
            load = fnum(week, "training_load", "training_load", "load")
            count = int(fnum(week, "count", "activities", default=0))
            fitness = fnum(week, "fitness")
            fatigue = fnum(week, "fatigue")
            if not time_s and not distance_m and not load and not count \
                    and fitness is None and fatigue is None:
                continue  # empty placeholder week (e.g. pre-history years)
            zones = week.get("time_in_zones", week.get("timeInZones"))
            rows[ws] = {
                "week_start": ws,
                "activities": count,
                "time_s": time_s,
                "distance_m": distance_m,
                "elev_gain_m": fnum(week, "elevation_gain", "elev_gain", "eg"),
                "training_load": load,
                "fitness": fnum(week, "fitness"),
                "fatigue": fnum(week, "fatigue"),
                "form": fnum(week, "form"),
                "ramp_rate": fnum(week, "ramp_rate", "rampRate"),
                "avg_weight_kg": fnum(week, "weight"),
                "time_in_zones": json.dumps(zones) if zones else "",
            }
            cats = week.get("byCategory", week.get("by_category")) or []
            if isinstance(cats, dict):
                cats = [
                    {"category": k, **v} if isinstance(v, dict) else {"category": k, "time": v}
                    for k, v in cats.items()
                ]
            for cat in cats:
                if not isinstance(cat, dict):
                    continue
                label = clean_text(
                    cat.get("category") or cat.get("type") or cat.get("id") or cat.get("name")
                )
                if not label:
                    continue
                by_category.append({
                    "week_start": ws,
                    "category": label,
                    "activities": int(fnum(cat, "count", "activities", default=0)),
                    "time_s": int(fnum(cat, "time", "moving_time", default=0)),
                    "distance_m": fnum(cat, "distance"),
                    "training_load": fnum(cat, "training_load", "load"),
                })
        print(f"  weekly {year}: total weeks so far {len(rows)}", flush=True)
        year += 1
        time.sleep(0.3)
    return list(rows.values()), by_category


def compute_decoupling(api: Api, acts: list[dict], since: date, min_seconds: int) -> list[dict]:
    """HR decoupling from streams for long runs: (r1-r2)/r1*100, halves by time."""
    results: list[dict] = []
    candidates = [
        a for a in acts
        if a.get("sport_group") == "run"
        and (fnum(a, "moving_time_s", "moving_time", "movingTime", default=0) or 0) >= min_seconds
        and parse_ts(a.get("start_utc") or a.get("start_date")) >= since.isoformat()
    ]
    print(f"  decoupling: computing for {len(candidates)} long runs since {since}", flush=True)
    for idx, act in enumerate(candidates, 1):
        aid = act.get("id")
        try:
            streams = api.get(f"/activity/{aid}/streams", {"types": "time,heartrate,velocity_smooth"})
        except urllib.error.HTTPError as err:
            print(f"    [{idx}/{len(candidates)}] id={aid} HTTP {err.code}; skipped", flush=True)
            continue
        if isinstance(streams, list):
            streams = {s.get("type"): s.get("data", s.get("series")) for s in streams}
        times = streams.get("time") or []
        hrs = streams.get("heartrate") or streams.get("hr") or []
        speeds = streams.get("velocity_smooth") or streams.get("velocity") or []
        if not (times and hrs and speeds and len(times) == len(hrs) == len(speeds)):
            continue
        samples = [
            (t, h, v)
            for t, h, v in zip(times, hrs, speeds)
            if t is not None and h and v is not None and v >= 0.5
        ]
        if len(samples) < 20:
            continue
        mid_t = (samples[0][0] + samples[-1][0]) / 2
        halves = ([], [])
        for t, h, v in samples:
            halves[0 if t <= mid_t else 1].append((h, v))
        ratios = []
        for half in halves:
            spd_dt = sum(v * 1.0 for _, v in half)
            hr_dt = sum(h * 1.0 for h, _ in half)
            if spd_dt <= 0 or hr_dt <= 0:
                ratios = []
                break
            ratios.append(spd_dt / hr_dt)  # aerobic efficiency: m per beat
        if len(ratios) == 2 and ratios[0] > 0:
            pct = (ratios[0] - ratios[1]) / ratios[0] * 100
            start = parse_ts(act.get("start_utc") or act.get("start_date") or act.get("start_local"))
            results.append({
                "activity_id": aid,
                "activity_start": start,
                "name": clean_text(act.get("name")),
                "decoupling_pct": round(pct, 2),
                "minutes": round(samples[-1][0] / 60.0, 1),
            })
        if idx % 25 == 0:
            print(f"    ... {idx}/{len(candidates)}", flush=True)
        time.sleep(0.4)
    return results


def write_csv(path: Path, columns: list[tuple[str, str]], rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[c for c, _ in columns], extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {c: "" if row.get(c) is None else row.get(c) for c, _ in columns}
            )


def build_db() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    tables = [
        ("activities", ACTIVITY_COLUMNS, "activities.csv"),
        ("weekly_summary", WEEKLY_COLUMNS, "weekly_summary.csv"),
        ("weekly_by_category", BYCATEGORY_COLUMNS, "weekly_by_category.csv"),
        ("decoupling_calc", DECOUPLING_COLUMNS, "decoupling.csv"),
    ]
    statements = []
    for table, columns, filename in tables:
        cols = ", ".join(f"'{name}': '{sql}'" for name, sql in columns)
        statements.append(
            f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv("
            f"'{RAW / filename}', header=true, nullstr='', columns={{{cols}}});"
        )
    statements.append("CHECKPOINT;")
    # anfra embeds an older DuckDB that cannot read files written in DuckDB 2.x's
    # new default storage format. Build in a temp file, then re-export into the
    # final DB using the widely-readable v0.10.0 storage format (readable by
    # DuckDB >= 0.10, including anfra's embedded driver and the 2.x CLI).
    build_path = DB_PATH.with_suffix(".build.duckdb")
    export_dir = DB_PATH.parent / ".build_export"
    if build_path.exists():
        build_path.unlink()
    if export_dir.exists():
        shutil.rmtree(export_dir)
    subprocess.run(
        ["duckdb", str(build_path)],
        input="\n".join(statements),
        text=True,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["duckdb", str(build_path), "-no-agent", "-c",
         f"EXPORT DATABASE '{export_dir}' (FORMAT parquet);"],
        check=True, capture_output=True,
    )
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        ["duckdb", "-no-agent", "-c",
         f"ATTACH '{DB_PATH}' AS final (STORAGE_VERSION 'v0.10.0');"
         f"USE final; IMPORT DATABASE '{export_dir}';"],
        check=True, capture_output=True,
    )
    shutil.rmtree(export_dir)
    build_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2006-01-01", help="backfill floor (YYYY-MM-DD)")
    parser.add_argument("--decoupling-since", default=None, help="compute stream decoupling for long runs since this date")
    parser.add_argument("--min-long-run-seconds", type=int, default=4500)
    parser.add_argument("--skip-decoupling", action="store_true")
    parser.add_argument("--skip-db", action="store_true", help="only write data/raw files")
    parser.add_argument("--build-only", action="store_true", help="rebuild DuckDB from existing data/raw files, skip API sync")
    parser.add_argument("--max-pages", type=int, default=500)
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("INTERVALS_ICU_API_KEY")
    athlete_id = env.get("INTERVALS_ICU_ATHLETE_ID", "8175042")
    if args.build_only:
        print("Building data/running.duckdb from existing data/raw files ...", flush=True)
        build_db()
        print(f"Done. DB: {DB_PATH}", flush=True)
        return 0
    if not api_key:
        print(
            "ERROR: INTERVALS_ICU_API_KEY not set.\n"
            f"Create {ROOT / '.env'} with:\n  INTERVALS_ICU_API_KEY=<your key>\n"
            "  INTERVALS_ICU_ATHLETE_ID=8175042",
            file=sys.stderr,
        )
        return 1

    since = date.fromisoformat(args.since)
    RAW.mkdir(parents=True, exist_ok=True)
    api = Api(api_key)

    print(f"Syncing activities since {since} ...", flush=True)
    acts = sync_activities(api, athlete_id, since, args.max_pages)
    # Strava-era entries are stubs (intervals.icu does not serve Strava
    # activities over the API: just id/date/source + a _note) — keep the raw
    # NDJSON complete but exclude stubs from the analytics table.
    data_acts = [a for a in acts if not a.get("_note") and (a.get("type") or a.get("distance") or a.get("moving_time"))]
    rows = [activity_row(a) for a in data_acts]
    (RAW / "activities.ndjson").write_text(
        "\n".join(json.dumps(a, default=str) for a in acts) + ("\n" if acts else "")
    )
    runs = sum(1 for r in rows if r["sport_group"] == "run")
    print(f"Activities: {len(rows)} unique ({runs} runs) — {api.calls} API calls so far", flush=True)

    print("Syncing weekly summaries ...", flush=True)
    weekly, weekly_cats = sync_weekly(api, athlete_id, since)
    (RAW / "weekly_summary.ndjson").write_text(
        "\n".join(json.dumps(w, default=str) for w in weekly) + ("\n" if weekly else "")
    )
    print(f"Weekly summaries: {len(weekly)} weeks, {len(weekly_cats)} by-category rows", flush=True)

    decoupling: list[dict] = []
    if args.decoupling_since and not args.skip_decoupling:
        decoupling = compute_decoupling(
            api, rows, date.fromisoformat(args.decoupling_since), args.min_long_run_seconds
        )
        print(f"Decoupling: {len(decoupling)} long runs computed", flush=True)

    write_csv(RAW / "activities.csv", ACTIVITY_COLUMNS, rows)
    write_csv(RAW / "weekly_summary.csv", WEEKLY_COLUMNS, weekly)
    write_csv(RAW / "weekly_by_category.csv", BYCATEGORY_COLUMNS, weekly_cats)
    write_csv(RAW / "decoupling.csv", DECOUPLING_COLUMNS, decoupling)

    if not args.skip_db:
        print("Building data/running.duckdb ...", flush=True)
        build_db()
    print(f"Done. {api.calls} API calls total. DB: {DB_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
