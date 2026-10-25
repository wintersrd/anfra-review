# running-analytics

Personal running & training analytics over 10+ years of intervals.icu history,
built as an [anfra](https://github.com/holistics/anfra) data app on a local
DuckDB file.

## What's inside

| Path | Purpose |
| --- | --- |
| `scripts/sync_intervals_icu.py` | Full-history sync from the intervals.icu API → `data/raw/*` → `data/running.duckdb` |
| `models/*.model.aml` | Semantic models: `activities`, `weekly_summary`, `weekly_by_category`, `decoupling_calc` |
| `datasets/running_analytics.dataset.aml` | Dataset with derived metrics (pace, weighted HR, run-only filters, aerobic efficiency) |
| `docs/anfra-framework-review.md` | anfra framework review: strengths, weaknesses, issues | `apps/running.html` | solutions |
| `apps/running.html` | One-page dashboard: fitness (CTL/ATL/TSB), volume & consistency, speed trends, surface splits (road/trail/indoor), stride length & pace distribution, HR decoupling, hilliness, pace vs temperature — Great Wave (ukiyo-e) themed |

Schema is sport-agnostic by design (v2 will add cycling + strength views):
`activities` carries every sport with a `sport_group` dimension and watts fields.

## Setup

```bash
cp .env.example .env        # add your INTERVALS_ICU_API_KEY (never committed)
python3 scripts/sync_intervals_icu.py            # full backfill (~a decade)
# optional: compute HR decoupling for long runs since a date (streams API):
python3 scripts/sync_intervals_icu.py --decoupling-since 2024-01-01

The DB is written in DuckDB storage format `v0.10.0` automatically — anfra's embedded
DuckDB engine can't read DuckDB 2.x's new default format, so don't rebuild the file with
the plain `duckdb` CLI (use `--build-only`).
~/.anfra/bin/anfra validate                      # semantic layer check
~/.anfra/bin/anfra serve                         # http://127.0.0.1:7878/apps/running
```

## Notes

- Weekly fitness/fatigue/form (CTL/ATL/TSB) and ramp rate come from
  intervals.icu's own athlete summary; decoupling is computed locally from
  streams for runs ≥ 75 min (first-half vs second-half HR/speed efficiency).
- `.env` and `.anfra/data_sources.yml` are git-ignored. DuckDB needs no
  credentials; the API key only lives in `.env`.
