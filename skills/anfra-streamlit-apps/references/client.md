# anfra_client for Streamlit app builders

The live data layer (`<name>_queries_aql.py`) talks to `anfra serve` over MCP
through the repo's `anfra_client` SDK. This file is the complete surface you
may use, the operational rules around the server, and the gotchas that have
actually cost builds time. Do not invent APIs; everything below is proven
working shapes.

## Client construction

```python
from anfra_client import AnfraClient, Filter, between, is_in

DATASET = "running_analytics"  # the fqn from `anfra show`
DATA_SOURCE = "running"  # data source key for .sql() passthrough
TIMEZONE = "Europe/Paris"  # the athlete's/org's local timezone


@st.cache_resource
def get_client() -> AnfraClient:
    return AnfraClient.from_env(dataset=DATASET)
```

`from_env` reads `ANFRA_MCP_URL` (default `http://127.0.0.1:7878/mcp`).
`get_client().ping()` → bool; use it in tests to skip-with-reason when the
server is down.

## Queries

```python
res = get_client().query(
    dimensions=["activities.date"],  # plain model.field
    measures={"km": "cycle_distance_km"},  # alias -> dataset metric
    filters=[
        "activities.ride_type is not null",  # string AQL condition
        between("activities.date", frm, to),  # helper
        is_in("activities.ride_type", ["road"]),
    ],  # helper
    order_by=["day asc"],  # alias (+ asc|desc)
    timezone=TIMEZONE,
)
df = res.frame()  # -> pandas DataFrame
```

Element forms: `"model.field"` or `(alias, "expr")` in `dimensions`/
`measures`; `measures` accepts a dict `alias -> metric` (preferred) or list
of pairs. Row keys in the frame are the aliases. Paginated queries:
`page=1, page_size=N` with `order_by=["<alias> desc"]` — the trick for
"latest date" when the date dimension isn't aggregatable.

### Custom dimensions and metrics (computed in AQL, not pandas)

```python
# bucket / band as a dimension:
custom_dimensions = {"activities.power_zone": _zone_case()}  # case(when:,then:,else:)
custom_dimensions = {"activities.temp_bucket5": "floor(activities.avg_temp_c / 5) * 5"}
# aggregate over another model in the same dataset:
custom_metrics = {"weight_kg": "weekly_summary | avg(weekly_summary.avg_weight_kg)"}
```

Custom dimensions are referenced **by their full dotted path** (`activities.power_zone`)
in `dimensions`, `order_by` and `is_in`. `case()` arms use `when: expr, then: 'label'`
with an `else:`; labels with ranges use en-dashes (U+2013) like `PACE_BUCKETS`/`CADENCE_BUCKETS`.

### Metric expressions over model measures

`(alias, "(model | sum(field * field)) / model.total_time_s")` — duration-
weighted means as AQL pipe expressions. Dataset metrics used *inside* model
expressions must be referenced qualified (`activities.total_time_s`).

### `.sql()` passthrough (rare)

`get_client().sql("SELECT …", data_source=DATA_SOURCE)` — for metadata the
semantic layer genuinely cannot express (e.g. min/max date bounds). Rare;
reaching for it twice means the AML is missing something — fix the AML.

## Caching and env

- Client: `@st.cache_resource`. Query functions: `@st.cache_data(ttl=300)`.
- Env overrides (fixture DB paths, feature constants like `CYCLING_FTP_WATTS`)
  are read **at call time**, never at import, so tests can flip them and
  rerun in-process. `""`/`"0"`/garbage semantics must be pinned by unit tests.
- Never print or log `.env` contents or API keys.

## Server, locks, ports

- **`anfra serve` owns the DuckDB lock.** Everything in-process goes through
  the server (that's why the live layer exists). The SQL oracle reads the
  **reader snapshot** (`data/*_reader.duckdb`), which stays readable while
  serve runs — that is the only sanctioned direct DuckDB access, and only
  from the oracle/tests.
- **Storage format rule**: the warehouse is DuckDB `v0.10.0`. Rebuild only
  via the repo sync script (`--build-only`), which converts formats; never
  `CREATE TABLE` with a plain `duckdb` CLI, or anfra's engine fails on every
  query with `initialize driver: internal error`. After any rebuild, restart
  `anfra serve`.
- **Ports**: multiple `anfra serve` instances are common (parallel builds on
  one machine). Pin yours: `anfra serve --addr 127.0.0.1:<port>` and export
  `ANFRA_MCP_URL=http://127.0.0.1:<port>/mcp` for the app and tests. A
  foreign server silently owning the default port produces "field not found"
  errors from a *stale warehouse* — always suspect the port before the query.
- `anfra validate` after every AML change; `anfra ingest` if lineage panels
  must reflect it.

## AQL gotchas (each one bit a real build)

1. **Date comparisons need the date literal**: `activities.week_start <= @2026-10-15`,
   not `<= '2026-10-15'` — quoted strings fail the server typecheck.
   Relative windows: `"activities.date matches @(last 90 days)"`.
2. **Filter by dimension name, not column name**: raw columns exposed via
   hidden dims (e.g. `hr_decoupling` over `decoupling`) are addressed by the
   *dim* path in conditions.
3. **Model measures vs raw dims**: e.g. `weekly_summary.ctl/atl/tsb` are
   *measures* (aggregate them); `fitness/fatigue/form` are raw dimensions
   (select/compare directly). `anfra show` says which is which — read it.
4. **Multi-element `{...}` blocks need commas** between elements.
5. **`st.cache_data` outside a Streamlit runtime** (smoke scripts) warns about
   missing ScriptRunContext and shows spinners — harmless; the values return
   fine.
6. **DuckDB Python API rejects `:name` params** in the oracle layer — use `?`
   placeholders with a list (or a `{"1": …}` dict) of values.
7. **Timestamps from `.frame()`/`fetchdf()`** are pandas `Timestamp`s; call
   `.date()` or slice `[:10]` before treating them as `datetime.date`, and
   never put a bare `Timestamp` where an ISO date string is expected.
