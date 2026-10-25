# running-analytics

Personal running & training analytics over 14 years of intervals.icu history,
built on a local DuckDB file with an [anfra](https://github.com/holistics/anfra)
semantic layer. Two frontends consume the same truth definitions: the native
anfra dashboard and a Streamlit app wired through anfra's MCP server.

## What's inside

| Path | Purpose |
| --- | --- |
| `scripts/sync_intervals_icu.py` | Full-history sync from the intervals.icu API → `data/raw/*` → `data/running.duckdb` |
| `models/*.model.aml` | Semantic models: `activities`, `weekly_summary`, `weekly_by_category`, `decoupling_calc` |
| `datasets/running_analytics.dataset.aml` | Dataset with derived metrics (pace, weighted HR, run-only filters, aerobic efficiency) |
| `docs/anfra-framework-review.md` | anfra framework review: strengths, weaknesses, issues → solutions |
| `apps/running.html` | One-page dashboard: fitness (CTL/ATL/TSB), volume & consistency, speed trends, surface splits (road/trail/indoor), stride length & pace distribution, HR decoupling, hilliness, pace vs temperature — Great Wave (ukiyo-e) themed |
| `streamlit_app/` | Streamlit port of the same dashboard (Plotly, day/night toggle, sport cross-filter); live data layer is `queries_aql.py` (AQL via `anfra_client`), with `queries.py` kept as the SQL test oracle — see below |
| `anfra_client/` | Python SDK over anfra's MCP server: typed logical-query API, error hierarchy, mock transport — **the boundary new data apps should code against** |
| `tests/` | Four-layer suite (unit / integration / anfra / charts) + client SDK tests, capability matrix, frame edge cases, record/replay smoke, live AppTest |
| `docs/anfra-client-guide.md` | Guide: build a new data app on the anfra backend with `anfra_client` (quickstart, error handling, testing patterns) |
| `AGENTS.md` | Development guide for AI agents (start here) |
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

## Architecture: anfra as the backend, apps as consumers

The Streamlit app's live data layer is `streamlit_app/queries_aql.py` — every
query is expressed as AQL over the anfra MCP. `queries.py` (raw SQL) is kept
as the SQL test oracle; an equivalence suite asserts both layers agree.

`anfra serve` owns the DuckDB file, the semantic model (AML), and the query
engine. Data apps — the native anfra dashboard, the Streamlit app, the next
app you build — are consumers:

- `anfra_client/` — typed Python SDK over anfra's MCP endpoint: express
  queries as logical elements (dimensions / measures / typed filters), get
  rows or DataFrames back, with a closed error hierarchy and a mock transport
  for hermetic tests. Start here: **docs/anfra-client-guide.md**.
- `streamlit_app/queries_aql.py` — the live data layer of the Streamlit app:
  all 22 query functions as AQL through the client, equivalence-tested
  against the SQL oracle (`queries.py`).

## Streamlit app

Same data, same charts, Great Wave styling — now AQL-backed via `anfra_client`:

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
uv run pytest                 # full suite: unit + integration + anfra + charts
uv run pytest -m unit         # fast pure-function layer only
uv run pytest -m integration  # fixture-DuckDB layer (no network, no API key)
```

Server-dependent tests split by access path — run the half you need:

```bash
uv run pytest -m anfra --ignore=tests/anfra    # MCP live tests: needs `anfra serve` RUNNING
uv run pytest tests/anfra tests/charts         # CLI + chart harness: needs `anfra serve` STOPPED (DuckDB lock)
```

Four layers, each guarding a class of bug we actually hit:

| Layer | Guards against |
| --- | --- |
| `unit` | sync-script logic (sport mapping, decoupling math + sign convention, pagination, week dedupe), theme palette invariants, SQL fragment builders, `anfra_client` behavior offline (envelope parsing, retries, session handling, typed errors, the Pythonic `query()` surface) |
| `integration` | DB build + derived columns (run_surface, stride guard), data-quality invariants (unique ids, ≤53 weeks/year, referential integrity), all 22 streamlit queries against the fixture DB, AQL↔SQL equivalence (24 tests, pinned tolerances + documented divergences), offline record/replay app smoke, full app.py render smoke test |
| `anfra` — MCP live (`tests/anfra_client/`, equivalence, AppTest) | `anfra serve` **running** | client SDK against the real server, the engine capability matrix (operator vocabulary, HAVING rule, paging, joins, timezone), AQL↔SQL equivalence, live Streamlit AppTest end-to-end |
| `anfra` — CLI + `charts` (`tests/anfra/`) | `anfra serve` **stopped** (DuckDB lock) | `anfra validate`, every AQL query embedded in `apps/running.html` executed via CLI, ECharts SSR harness rendering all 16 charts headlessly (caught the echarts visualMap crash that blanked the dashboard) |

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
