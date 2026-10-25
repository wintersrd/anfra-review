# AGENTS.md — running-analytics

Training analytics over 14 years of intervals.icu history: a DuckDB warehouse,
an anfra semantic layer (AML/AQL) as the single source of truth, and two
consumer frontends — the native anfra dashboard (`apps/running.html`) and a
Streamlit app (`streamlit_app/`) wired through anfra's MCP server via the
`anfra_client` Python SDK.

## Layout

| Path | Contents |
| --- | --- |
| `scripts/sync_intervals_icu.py` | intervals.icu API → `data/raw/*` → `data/running.duckdb` (+ `data/running_reader.duckdb` snapshot) |
| `models/*.model.aml`, `datasets/*.dataset.aml` | Semantic layer (truth definitions live here, not in apps) |
| `apps/running.html` | Native anfra dashboard (21 queries, ECharts, single file) |
| `streamlit_app/` | Streamlit app: `app.py` (UI), `queries_aql.py` (live AQL data layer), `queries.py` (SQL **test oracle** — do not delete), `theme.py` |
| `anfra_client/` | Domain-agnostic Python SDK over the anfra MCP (`client`, `transport`, `mock`, `filters`, `models`, `errors`) |
| `tests/` | `unit/`, `integration/`, `anfra/`, `charts/`, `anfra_client/` |
| `docs/` | `anfra-framework-review.md` (evaluation incl. Streamlit comparison), `anfra-client-guide.md` (SDK guide) |
| `data/raw/` | Committed sync outputs (CSV/NDJSON) — the test fixture source |

## Golden rules

1. **DuckDB storage format is `v0.10.0` — always.** anfra's embedded engine
   cannot read DuckDB 2.x's new default format (every query fails with
   `initialize driver: internal error`). Only rebuild the DB through the sync
   script (`python3 scripts/sync_intervals_icu.py --build-only`), which
   exports/imports into the compatible format. Never build with the plain
   `duckdb` CLI.
2. **`anfra serve` holds the DuckDB file lock.** CLI queries and the `anfra`/
   `charts` test layers fail or skip while it runs. Restart `anfra serve`
   after every DB rebuild. The Streamlit app is immune (it reads the
   `running_reader.duckdb` snapshot).
3. **Streamlit restart semantics:** edits to `app.py` need only a browser
   rerun; edits to `queries.py` / `queries_aql.py` / `theme.py` (imported
   modules) require killing and relaunching the streamlit process.
4. **`curl 200` does not mean the app works.** Streamlit serves its shell
   without executing the script. The real smoke gate is the live AppTest
   (`tests/integration/test_app_apptest.py`), which runs the whole app.
5. **`queries.py` is the SQL oracle.** The equivalence suite
   (`tests/integration/test_queries_aql_equiv.py`) is the contract between
   SQL and AQL. Divergences are pinned and documented, not silently tolerated
   (e.g. `kpi_week_distance` reads the last *complete* week in AQL because
   `week_start` is a stored column).
6. **Data fingerprints are pinned** in `tests/integration/test_build_db.py`
   (row counts per table). Update them in the same commit as a deliberate
   re-sync.
7. **Secrets stay in `.env`** (`INTERVALS_ICU_API_KEY`). Never print, commit,
   or echo them. `.env` and `.anfra/data_sources.yml` are git-ignored.
8. **The sync script needs its custom User-Agent** (`running-analytics-sync/1.0`);
   urllib's default is Cloudflare-blocked (error 1010). Don't strip headers.
9. **AQL gotchas:** multi-element `{...}` blocks need commas between elements
   (the `anfra_client` renderer handles this); `weekly_summary.ctl/atl/tsb`
   are model *measures* while `fatigue/form/fitness/training_load/ramp_rate`
   are raw dimensions; dataset metrics must be referenced qualified when used
   as model measures (e.g. `activities.total_time_s`); `PACE_BUCKETS` labels
   contain en-dashes.
10. **Pre-commit must pass** (ruff check + format + unit pytest layer).
    Coverage floor is 70% (`--cov-fail-under`); use `--no-cov` for partial
    marker runs. Conventional commits (`feat:`, `fix:`, `test:`, `docs:`).

## Handy commands

```bash
python3 scripts/sync_intervals_icu.py --build-only   # rebuild DB from committed data/raw
python3 scripts/sync_intervals_icu.py --decoupling-since 2024-01-01   # full sync + decoupling
~/.anfra/bin/anfra validate                          # semantic layer check
~/.anfra/bin/anfra serve                             # http://127.0.0.1:7878/apps/running
uv run streamlit run streamlit_app/app.py            # http://localhost:8501
uv run pytest                                        # full suite
uv run pytest -m unit --no-cov                       # fast loop
uv run pytest -m "anfra"                             # needs anfra serve STOPPED (lock)
uv run pytest tests/integration/app_replay.py --no-cov  # re-record MCP fixtures (server up)
uv run ruff check . && uv run ruff format --check . && uv run mypy .
```

## anfra MCP contract (quick facts)

Endpoint `http://127.0.0.1:7878/mcp` (streamable HTTP JSON-RPC), tools
`core.query` / `core.query.compile` / `core.lineage` / `core.search` / `core.show`.
`core.query`: top-level `query` (AQL) + `dataset` + `input.{filters,conditions,sorts}`,
optional `page`/`page_size`/`timezone`. Response envelope:
`{sql, aql, columns[{name, fieldName, db_type, isMeasure}], result{fields, records},
has_more, timings}`; errors arrive as HTTP 200 with `diagnostics` (compile) or
`violations` (validation) inside the payload. ~200ms/query. Full details and
consumer patterns: `docs/anfra-client-guide.md`. Record/replay fixtures live in
`tests/integration/replay_data/` — re-record after intentional query changes
(and commit them) so the offline smoke test stays truthful.

## Testing map

| Suite | Server | What it guards |
| --- | --- | --- |
| `unit` | indifferent | sync logic, client SDK offline behavior (envelope, retries, `query()` surface), theme invariants |
| `integration` (fixture DuckDB) | indifferent | DB build, data quality, all 22 AQL queries vs fixture, app render smoke |
| MCP live: `tests/anfra_client/test_live_anfra.py`, `test_capability_matrix.py`, `tests/integration/test_queries_aql_equiv.py`, `test_app_apptest.py` | **up** | client SDK against the real server, engine capability matrix, AQL↔SQL equivalence, full-app AppTest |
| CLI anfra + charts: `tests/anfra/` | **down** (DuckDB lock) | `anfra validate`, embedded app AQL via CLI, headless ECharts SSR of all 16 charts |

The split exists because MCP tests need the server *up* while CLI tests need
the DuckDB lock, which the server holds. All of them auto-skip with a reason
when their precondition isn't met; `ANFRA_LIVE_TESTS=0` force-disables the
MCP live tests. The lock caveat below is why `pytest -m "anfra or charts"`
alone is never the full story — check which half you ran.
