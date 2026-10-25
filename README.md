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
| `docs/anfra-framework-review.md` | anfra framework review: strengths, weaknesses, issues → solutions |
| `apps/running.html` | One-page dashboard: fitness (CTL/ATL/TSB), volume & consistency, speed trends, surface splits (road/trail/indoor), stride length & pace distribution, HR decoupling, hilliness, pace vs temperature — Great Wave (ukiyo-e) themed |
| `streamlit_app/` | Streamlit port of the same dashboard (Plotly, day/night toggle, sport cross-filter) — see below |
| `anfra_client/` | Python SDK over anfra's MCP server: typed logical-query API, error hierarchy, mock transport — **the boundary new data apps should code against** |
| `docs/anfra-client-guide.md` | Guide: build a new data app on the anfra backend with `anfra_client` (quickstart, error handling, testing patterns) |
| `.streamlit/config.toml` | Streamlit base theme (Great Wave light palette) |

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

## Architecture: anfra as the backend, apps as consumers — the Streamlit app's live data layer is `streamlit_app/queries_aql.py` (AQL over the anfra MCP); `queries.py` remains as the SQL test oracle

`anfra serve` owns the DuckDB file, the semantic model (AML), and the query
engine. Data apps — the native anfra dashboard, the Streamlit app, the next
app you build — are consumers:

- `anfra_client/` — typed Python SDK over anfra's MCP endpoint: express
  queries as logical elements (dimensions / measures / typed filters), get
  rows or DataFrames back, with a closed error hierarchy and a mock transport
  for hermetic tests. Start here: **docs/anfra-client-guide.md**.
- `streamlit_app/queries_aql.py` — worked example: the KPI tier re-expressed
  as AQL through the client, equivalence-tested against the SQL module
  (`queries.py`, kept as the test oracle during the migration).

## Streamlit app

Same data, same 21-query surface, Plotly charts, Great Wave styling:

```bash
uv sync                                          # creates .venv (streamlit, plotly, duckdb)
uv run streamlit run streamlit_app/app.py        # http://localhost:8501
```

The app reads `data/running_reader.duckdb` — a read-only snapshot written
automatically after every DB build, so it never fights the anfra server for
the DuckDB write lock. Night mode and the sport cross-filter (click a slice in
"Hours by sport") live in-app; date/sport/surface filters are in the sidebar.

## Testing

```bash
uv run pytest                 # full suite (≈40s): unit + integration + anfra + charts
uv run pytest -m unit         # fast pure-function layer only
uv run pytest -m integration  # fixture-DuckDB layer (no network, no API key)
uv run pytest -m "anfra or charts"  # needs ~/.anfra/bin/anfra and NO running `anfra serve`
```

Four layers, each guarding a class of bug we actually hit:

| Layer | Guards against |
| --- | --- |
| `unit` | sync-script logic (sport mapping, decoupling math + sign convention, pagination, week dedupe), theme palette invariants, SQL fragment builders |
| `integration` | DB build + derived columns (run_surface, stride guard), data-quality invariants (unique ids, ≤53 weeks/year, referential integrity), all 21 streamlit queries, full app.py render smoke test |
| `anfra` | `anfra validate`, plus every AQL query embedded in `apps/running.html` executed against the live DB |
| `charts` | ECharts SSR harness (node): renders all 16 anfra charts headlessly and fails on any `setOption` throw — this caught the echarts visualMap crash that blanked the dashboard |

The integration fixture builds a DuckDB from the *committed* `data/raw` CSVs,
so tests are deterministic and need no network. Data fingerprints (row counts
per table) are pinned in `tests/integration/test_build_db.py` — update them in
the same commit as any deliberate re-sync. The anfra/chart layers auto-skip
while `anfra serve` holds the DuckDB file lock (stop the server to run them).
Coverage floor is 70% (`--cov-fail-under` in `pyproject.toml`); use
`--no-cov` for partial marker runs. Pre-commit runs ruff + the unit layer.

## Notes

- Weekly fitness/fatigue/form (CTL/ATL/TSB) and ramp rate come from
  intervals.icu's own athlete summary; decoupling is computed locally from
  streams for runs ≥ 75 min (first-half vs second-half HR/speed efficiency).
- `.env` and `.anfra/data_sources.yml` are git-ignored. DuckDB needs no
  credentials; the API key only lives in `.env`.
