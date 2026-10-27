---
name: anfra-streamlit-apps
description: Build or change a Streamlit data app over the anfra semantic layer — a Python app in the repo's `streamlit_app/` whose data layer queries datasets through the `anfra_client` SDK (AQL over MCP), backed by a SQL validation oracle, equivalence tests, and a headless full-app gate. Use for any dashboard, report, page or interactive analysis over the repo's datasets when the app must be Python/Streamlit rather than an anfra HTML Data App.
---

# Building an Anfra Streamlit App

An **Anfra Streamlit App** is a Python module in the repo's `streamlit_app/`
(`cycling_app.py`, `sales_app.py`, …) rendered by `streamlit run`, with its
data supplied by the anfra semantic layer through the `anfra_client` SDK. The
SDK supplies data; every pixel is Streamlit's and yours.

The architecture is a law, not a suggestion — every rule below exists because
a build without it failed in a recorded way:

```
models/*.aml + datasets/*.aml      ← definitions live HERE and nowhere else
        │
   anfra serve (MCP)
        │
streamlit_app/<name>_queries_aql.py    ← live layer: anfra_client queries
streamlit_app/<name>_queries.py        ← SQL oracle: same answers, raw
                                        DuckDB over the reader snapshot;
                                        imported ONLY by tests
        │
streamlit_app/<name>_app.py            ← renders DataFrames; computes
                                        NOTHING a reader could distrust
        │
tests/…                                ← equivalence (oracle ≡ live) and
                                        AppTest (full app, headless) gates
```

- The app never opens the warehouse directly and never re-derives a
  definition. If a number the app needs has no field or metric, add it to the
  AML ([](../aml/) skill), not to Python.
- The oracle is not scaffolding to delete. It is the contract that the AQL the
  server actually executes means what the AML says it means.
- Acceptance is a test that runs the whole app with zero exceptions — not
  your eyes on a browser. Streamlit serves its shell without executing the
  script; `curl 200` proves nothing.

References, read when a step needs them:

- [references/client.md](references/client.md): the `anfra_client` surface you
  may use (query forms, filters, custom dimensions/metrics, `sql` passthrough,
  errors), plus server/env/lock rules and the AQL gotchas that have actually
  bitten. **Read it before writing the data layer; do not invent APIs.**
- [references/design.md](references/design.md): layout rhythm, theme tokens,
  the four states, cross-filter pattern, formatting and accessibility rules.
  Read it before writing the app.
- [references/testing.md](references/testing.md): the gate suite — fixture
  conftest, equivalence patterns, AppTest scenario checklist, server up/down
  matrix, commit sequencing. Read it before claiming anything works.
- [references/example/](references/example/): a complete minimal app (live
  layer, oracle, both test files) exercising every pattern. Start from it.

## 0. Keep the worklog

Create `WORKLOG.md` at the repo root (or append, if one exists) before any
code. Every entry timestamped, written **as the work happens** — a worklog
reconstructed at the end is a report, not a log:

```markdown
## 2026-10-26 16:45 — <step or decision>
- What was decided, and why (quote the spec clause).
- Issues hit + how resolved (the error text, the fix).
- Gate results (exact counts: "278 passed, coverage 88.86%").
```

Record as numbered **interpretation decisions** every place the spec is
ambiguous, with the interpretation chosen and who decided (you-recommended vs
owner-confirmed). A reader of the worklog alone must be able to reconstruct
every number on screen.

## 1. Learn the datasets — and the raw payload

```sh
~/.anfra/bin/anfra show                # every dataset: models, fields, metrics
~/.anfra/bin/anfra show <dataset fqn>  # one dataset, full field list
```

The fqn is what the client's `dataset=` takes. A field is `model.field`
(`activities.date`); a dataset metric its bare name. A measure is already
aggregated: select it, never wrap it in `sum()` again. Read labels and
descriptions — they carry the modeler's caveats on grain, fan-out and which
date to use.

**Then interrogate the raw payload — this step is mandatory, not optional.**
The warehouse is not the source of truth; the sync script is, and sync
scripts drop fields. For every quantity the request implies (targets,
thresholds, reference values like FTP or pace zones), look for it in
`data/raw/*` (grep the NDJSON/CSV) *before* deciding it doesn't exist. In the
reference A/B build, the raw payload carried a per-activity FTP field the
warehouse never imported; the build that skipped this step hardcoded a
constant and mis-zoned ~4% of power data — the build that checked found it in
minutes.

Produce a **field inventory** in the worklog: one row per number the app will
show — semantic field/metric name, or "raw-only: <column>, needs AML + sync",
or "absent: <interpretation decided>". Fields that are raw-only get landed in
the AML and the sync script *first*, before any app code:

- extend the sync script (derived columns computed in SQL at build time, like
  `run_surface`/`ride_type`), rebuild with the sync script only — **never**
  build the DuckDB with the plain `duckdb` CLI (storage-format rule, see
  [references/client.md](references/client.md)) — then `anfra validate`, then
  restart `anfra serve`.

## 2. Agree on the design

Restate the request as one result the user can check ("weekly ride volume by
type for the selected window, with a donut that filters everything else").
Ask only what changes the numbers: what a business word means, which date
counts, what's excluded — each with your recommended answer. Record the
answers as interpretation decisions (step 0).

Then write the **declaration list**, one line per component, and get a yes
before writing code:

| Component | Data function(s) | Grain | Filters | Chart | Empty state |
| --- | --- | --- | --- | --- | --- |
| `weekly_distance` | `weekly_distance(from, to, types)` | week | date + type | line | names the filter |

plus: the KPI strip (value, delta, caption), the widget inventory (presets,
date range, type multiselect, theme toggle), which component is the
cross-filter source and which honor it, and the look (default theme tokens vs
user-supplied). State which functions honor the type filter and which are
date-only (the cross-filter source must be date-only so it stays stable while
filtering).

When the data cannot answer the request, say so and offer the nearest thing
it can.

## 3. Write and check the data layer — before any UI

Two files, written together, kept independent (the oracle must never import
the live layer or vice versa; constants are duplicated deliberately and a
unit test pins them equal):

- `<name>_queries_aql.py` — the live layer. `AnfraClient.from_env(dataset=…)`
  once, `@st.cache_resource`; every query function `@st.cache_data(ttl=300)`
  returning a DataFrame. Filters, custom dimensions and metric references per
  [references/client.md](references/client.md).
- `<name>_queries.py` — the oracle. Read-only DuckDB over the reader snapshot
  (`data/<repo>_reader.duckdb`), env-overridable path so AppTest can point it
  at a fixture (`$<NAME>_DB`). Same functions, same shapes, raw SQL.

Rules that keep the layers provably equal:

- **No view-layer math.** Bucketing, week/month truncation, weighted means,
  zero-fill of missing weeks — all inside both data layers as data functions.
  If a computation can't be expressed in AQL, do it in the live layer in
  pandas *and* mirror it in the oracle, and document the mechanism in the
  docstring (the equivalence test still pins the numbers).
- Row-level guards (`watts > 0`, `cadence > 40` — coast artifacts read 0) are
  mirrored as string conditions in the live layer so both layers filter
  identically.
- Constants (bucket edges, enums, thresholds) defined in both files, pinned
  equal by a unit test. Bucket labels with ranges use en-dashes.
- Every function runs headless before the app exists: a throwaway smoke that
  calls each one on the default window, an empty window, and a narrowed
  filter, printing rows/columns. Only when all pass do you write the app.

## 4. Write the app

Start from [references/example/](references/example/) — it already has the
import bootstrap, sidebar contract, four states, cross-filter, load log and
footer. Full rules in [references/design.md](references/design.md); the
non-negotiables:

- **Import bootstrap first** (the repo root must be on `sys.path` before
  `anfra_client` imports; Streamlit only puts the script's folder there).
- **Four states, every component**: success, empty (`st.info` naming the
  active filter, never a bare zero), error (`st.error`, app keeps rendering),
  loading (Streamlit's own). Wrap every data call in one `_run_query` helper
  that logs to `st.session_state.load_log` — key, milliseconds, row count —
  and renders `st.error` on failure instead of raising.
- **Diagnostics are a feature**: the load log renders in a collapsed expander
  in the footer. Its keys are the component handles you and the user will
  refer to changes by ("the `weekly_distance` block is slow").
- **Never encode a category by color alone**: shape or dash plus color, or a
  label on every mark. Every pointer interaction (donut cross-filter) has a
  keyboard/widget path (the type multiselect mirrors it).
- Window presets are data-relative (latest activity date − N days), bounds
  from the dataset's own clock; captions carry definition, window and
  exclusion counts.

## 5. Run the gates

In order; details and copy-paste patterns in [references/testing.md](references/testing.md):

1. **Equivalence**: oracle ≡ live layer on the default window, an empty
   window, and a narrowed filter — committed, marked to run only when
   `anfra serve` answers (skip with a reason otherwise).
2. **Full-app gate**: `AppTest.from_file(...)` runs the whole script — zero
   exceptions, the expected component count in the load log, no failed loads;
   plus reruns for an empty window, a narrowed filter, and every configured
   fallback (e.g. unset-FTP path).
3. **Repo gates**: `uv run ruff check .`, `ruff format --check .`, `mypy`,
   pre-commit, full pytest with the server up (mind the server up/down test
   matrix — some suites need serve running, some need the DuckDB lock free),
   `anfra validate` after any AML change.
4. Conventional commits (`feat:`, `fix:`, `test:`, `docs:`), staged so every
   commit keeps the unit layer green on its own (pre-commit stashes unstaged
   tracked files but not untracked ones — stage everything the tests import,
   or the hook will test against a half-tree).
5. Worklog gets the final gate table (exact pass counts and coverage).

## 6. Hand over

Tell the user, in their terms: what the page shows and how to use each
control, the exact run command (including the env vars that matter — serve
URL override, any feature constants), the interpretation decisions made and
which were owner-confirmed vs builder-chosen, and what was checked (gate
results) vs what only eyes can check (visual polish). Point at the load-log
keys as the vocabulary for change requests. A `127.0.0.1` URL opens only on
this machine; say so if it matters.

## Related skills
* [](../aml/) — add the fields and metrics an app needs.
* [](../write-aql/) — write and validate the queries.
* [](../setup-repo/) — set up the repo and its data source first.
