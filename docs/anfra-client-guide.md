# Building data apps on anfra with `anfra_client`

anfra is the **infrastructure backend**: it owns the database (DuckDB), the
semantic model (`models/*.model.aml`, `datasets/*.dataset.aml`), and the query
engine (AQL → SQL). Data applications are **thin consumers** of that backend
through the `anfra_client` Python package — they express logical query
elements and render results, never touching SQL or the DB file.

```
┌─────────────────────────────┐
│  anfra serve (port 7878)    │  ← infrastructure: DB + AML semantic layer + engine
│  DuckDB · AML · AQL→SQL     │     also serves the native anfra dashboard
└──────────────▲──────────────┘
               │ MCP (streamable HTTP, JSON-RPC) — tools: core.query, core.query.compile, …
┌──────────────┴──────────────┐
│  anfra_client (this package)│  ← the only boundary apps should code against
└──────▲──────────────▲───────┘
       │              │
┌──────┴──────┐ ┌─────┴──────┐
│ Streamlit   │ │ next app   │   ← N consumers, any domain, any UI framework
│ running app │ │ (own repo/ │
│ (consumer 1)│ │  dataset)  │
└─────────────┘ └────────────┘
```

## Quickstart (a new data app in ~20 lines)

```python
import streamlit as st
from anfra_client import AnfraClient, is_in, between

cx = AnfraClient.from_env(dataset="running_analytics")  # ANFRA_MCP_URL / .env

st.title("My new data app")

res = cx.query(
    dimensions=["activities.month"],
    measures=["total_distance_km"],
    filters=[
        is_in("activities.sport_group", ["run"]),
        between("activities.date", "2026-01-01", "2026-12-31"),
        "activities.is_race == true",  # free-form AQL, same list as typed filters
    ],
    order_by=["activities.month asc"],
)
st.bar_chart(res.frame().set_index("month")["total_distance_km"])
```

Run `anfra serve` first (the client cannot start it for you):

```bash
~/.anfra/bin/anfra serve     # repo root; apps + MCP on 127.0.0.1:7878
```

## The query surface

Everything hangs off one class, `AnfraClient`. `query()` is the default —
logical elements in, rows back, no AQL text to format:

| Method | Purpose |
| --- | --- |
| `query(dimensions=…, measures=…, custom_metrics=…, filters=…, order_by=…)` | **Default surface.** See element forms below. |
| `aql(query_text, filters=…)` | Raw AQL escape hatch — needed for query-local `case()` dimensions and anything the structured API can't say. Filters still go through the typed API. |
| `sql(query, data_source=…)` | Raw SQL (utilities, health checks). AQL is preferred; SQL bypasses the semantic layer. |
| `compile(query)` | AQL → SQL text without executing (debugging, equivalence tests). |
| `ping()` / `tools_list()` / `initialize()` | Health checks and introspection. |

**Element forms** — `dimensions` and `measures` each accept a single ref, a
list, or a mapping; aliases are derived from the last path segment and always
rendered explicitly, so result columns get clean, predictable names:

```python
cx.query(dimensions="activities.sport_group", measures="total_time_h")
# == cx.query(
#     dimensions=[("sport_group", "activities.sport_group")],
#     measures=[("total_time_h", "total_time_h")],
# )
```

**Query-local metrics** (`custom_metrics`) render as `metric name = expr;`
assignments before the explore — the AQL way to express semi-additive
KPIs (latest week, trailing averages) that dataset metrics can't say:

```python
res = cx.query(
    custom_metrics={
        "this_week_run_km": (
            "run_distance_km | where(activities.week_start == max(activities.week_start))"
        ),
    },
    measures=[("this_week", "this_week_run_km")],
    filters=["activities.week_start matches @(last 4 weeks)"],
    timezone="Europe/Paris",
)
```

`is_explore=False` renders only those assignments (no explore block): the
server compiles it and returns no rows — handy with `.sql`/`compile()` to
inspect what a metric compiles to.

**Filters** — typed objects and plain AQL strings mix freely in one list;
typed filters go to `input.filters`, strings/`Condition`s to
`input.conditions`, all ANDed *by the server* (never string-interpolated
into the query — this is what makes dynamic dashboards safe):

- `is_in(field, values)` — anfra's `is` operator is an IN-list (validated)
- `between(field, low, high)` — inclusive range; validated for dates (validated)
- `last(field, n, unit="day")` — relative windows (validated)
- `condition("…")` / `"…"` strings — free-form AQL conditions (validated)
- low-level `Filter(field=…, operator=…, values=…)` for unvalidated operators
  (`contains`, `is_not`, …) — anfra may accept them; we haven't pinned them.

Numbers are stringified automatically (anfra's MCP schema refuses JSON numbers
to avoid precision loss). Empty `is` filters are rejected client-side. Invalid
identifiers (metric names, aliases) are rejected client-side before any call.

**order_by**: `"hours desc"` / `"week_start"` (direction defaults to asc) or
`(alias, "desc")` tuples.

**Pagination**: `page=` / `page_size=` (≤10000 rows/page, `has_more` on the
result). **Timezone**: pass IANA names (`"Europe/Paris"`) for relative dates
and date truncation.

## Filter catalog

Server-validated operators for `input.filters` (probed against 0.13.3, pinned by
`tests/anfra_client/test_capability_matrix.py`):

| Operator | Values | Notes |
|---|---|---|
| `is` | list (>=1) | IN-list; empty rejected |
| `is_not` | list | negated IN |
| `between` | 2 values | inclusive; dates |
| `last` | ["N"] + `modifier` | relative window (`day`, ...) |
| `greater_than` / `less_than` | [v] | row-level (pre-aggregation) |
| `contains` / `starts_with` / `ends_with` | [v] | CASE-INSENSITIVE |
| `before` / `after` | [date] | date fields |

HAVING-style aggregated conditions: `Filter(field="model.field", operator=..., values=..., aggregation="sum")`
— `aggregation` applies to a dataset FIELD, never a metric (server rejects that).

Free-form conditions (`Condition` or plain strings) support the AQL expression
grammar: `not in`, `!=`, `is not null`, `in [...]`, `matches @(last N days)`.

## Record / replay (app smoke test)

`uv run python tests/integration/app_replay.py` records every MCP response the
app needs into `tests/integration/replay_data/` (committed). The full-app smoke
test replays them offline — no server needed — and doubles as an envelope
contract regression net. Re-record after re-syncs if you want fresh values
(structure alone keeps the smoke test valid).

## Reading results

`QueryResult` carries everything the server returned:

```python
res.rows  # list[dict] keyed by result column (alias) names
res.frame()  # pandas DataFrame; numeric strings coerced via column metadata
res.frame(coerce=False)  # raw wire values (everything is strings)
res.columns  # typed column metadata (db_type, semantic_type, is_measure)
res.sql  # the compiled SQL — great for debugging
res.has_more  # True if another page exists
res.timings  # server-side step timings
```

Column-name subtlety worth knowing: `fields`/`rows` use the **result column
name** (your alias); the column metadata's `fieldName` is the underlying
model field. `frame()` matches on the result name.

## Error handling — a closed hierarchy

Every failure raises a subclass of `AnfraError`, each with an actionable
`hint` (and `request_id` where the server provided one):

| Exception | Meaning | Typical app reaction |
| --- | --- | --- |
| `AnfraConnectionError` | Server unreachable / 5xx after retries | Show "backend down — start `anfra serve`" |
| `AnfraSessionError` | MCP session repeatedly rejected | Server crash-looping; restart it |
| `AnfraCompileError` | Bad AQL (unknown field/metric, syntax) | Has `.diagnostics` with line/column — render them |
| `AnfraValidationError` | Bad input (unknown filter field, arity) | Has `.violations` with field paths |
| `AnfraContractError` | Response envelope doesn't match the pinned contract | **Regression tripwire** — pin the anfra version |

`AnfraQueryError` is the parent of compile/validation errors; catch
`AnfraError` at app edges and render `str(e)` (message + hint).

Retry policy (built in): transport failures and 5xx retry twice with backoff;
stale sessions re-handshake once; **query errors never retry** (they are
deterministic).

```python
from anfra_client import AnfraError, AnfraCompileError

try:
    res = cx.aql(user_edited_aql)
except AnfraCompileError as e:
    st.error(f"Query error: {e}")
    st.json(e.diagnostics)
except AnfraError as e:
    st.error(str(e))
```

## Testing your app (hermetic by design)

The package separates **transport** from **protocol**, so tests need no
server:

```python
from anfra_client import AnfraClient
from anfra_client.mock import MockTransport, tool_result_body, success_payload

t = MockTransport()
t.script_initialize(session_id="mock-sid")
t.script_tool(
    "core.query",
    [
        tool_result_body(
            1,
            success_payload(
                ["sport", "hours"],
                [["run", "249.9"]],
                columns=[
                    {"name": "sport", "fieldName": "sport_group", "db_type": "VARCHAR"},
                    {"name": "hours", "fieldName": "total_time_h", "db_type": "DOUBLE"},
                ],
            ),
        )
    ],
)
cx = AnfraClient(url="mock://", dataset="my_dataset", transport=t)

res = cx.query(measures={"hours": "total_time_h"})
assert res.rows[0]["hours"] == "249.9"
assert t.tool_calls("core.query")[0].arguments["input"] == {}  # payload assertions
```

- `t.requests` records every JSON-RPC payload — assert session headers,
  filter shapes, pagination exactly.
- `tests/anfra_client/fixtures/*.sse.txt` are **recordings of real server
  responses** (success, compile error, validation error). Replaying them in
  unit tests keeps the client honest against the actual wire format.
- Live regression tests (`pytest -m anfra`) re-validate the operator matrix
  against a running server; they skip automatically when it's down.
- When `AnfraContractError` fires after an anfra upgrade: the MCP envelope
  changed. Re-record fixtures (`tests/anfra_client/fixtures/`), adjust the
  parser if needed, and pin the new version.

## Ops notes

- **One writer per DuckDB file.** `anfra serve` holds the lock; all queries
  should flow *through* it (that's what this client does). Don't open the
  same file with the duckdb CLI / python package while serving.
- The server executes on its own connection, so the client and the native
  anfra dashboard coexist safely.
- Client defaults: `ANFRA_MCP_URL` env or `http://127.0.0.1:7878/mcp`,
  15s timeout, 2 transport retries. The client is sync + thread-safe
  (Streamlit reruns share one instance fine).
- Contract status (validated against **anfra 0.13.3**, 2026-10): tools
  `core.query`, `core.query.compile`; arguments `dataset`, `query`,
  `input.filters` (`is`/`between`/`last`+`modifier`), `input.conditions`,
  `input.sorts`, `page`/`page_size`, `timezone`, `lang`/`data_source` for SQL;
  responses as SSE `data:` lines. Anything not listed here is unpinned.

## Where to put what (conventions)

- **Semantic definitions** (metrics, relationships, grain rules) live in
  `models/` + `datasets/` AML — the single source of truth. Apps reference
  them by name; they never re-implement metric math.
- **App-specific logic** (chart transforms, bucketing for display, session
  state) lives in the app.
- **Domain data layers** (e.g. `streamlit_app/queries_aql.py`) wrap the
  client with domain-named functions returning DataFrames — one module per
  app, all sharing this package.
