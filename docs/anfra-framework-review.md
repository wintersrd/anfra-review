# anfra Framework Review

Hands-on assessment after building a full production app with anfra: a running/training
analytics dashboard (`apps/running.html`, 21 queries, 16 ECharts visualizations) on top of
~14 years of intervals.icu data in a DuckDB file. ~30 hours of work including data
engineering, semantic modeling, app building, and debugging.

> anfra (github.com/holistics/anfra): local-first, git-based semantic layer + "data app"
> framework. CLI (`anfra init/validate/serve/query/ingest/lineage`), AML models/datasets
> with an AQL metric language, and single-file HTML apps that declare queries and controls
> in markup and render with any JS charting library. Serves at `127.0.0.1:7878`.

---

## How it works (as experienced)

```
repo/
├── .anfra/data_sources.yml      # connections (duckdb path, postgres, clickhouse, ...)
├── models/*.model.aml           # tables: dimensions (@sql) + measures
├── datasets/*.dataset.aml       # bundles models + relationships + dataset metrics + view groups
└── apps/*.html                  # one self-contained page per app (markup + CSS + JS + queries)
```

- **AML** maps physical tables into a semantic layer. Dimensions can be raw columns or
  `@sql` expressions; metrics are AQL (e.g. time-weighted averages with conditional
  filters — "runs only", "Σx·t / Σt").
- **AQL** queries are declared in the app HTML or run from the CLI:
  `anfra query --dataset my_data 'explore { measures { x: my_metric } }'`.
- **Apps** are declarative: `data-anfra-container/block/query/control` attributes mark up
  containers, chart mounts, and filter controls; a small JS SDK (`app.createQuery`,
  `app.subscribe(render)`, `mapCrossFilter`, `select`) feeds rows to your own rendering
  code. We used ECharts; anything that draws in a browser works.
- The runtime serves apps inside a **sandboxed iframe** (`sandbox="allow-scripts"`,
  injected via `srcdoc`) with a postMessage RPC bridge to the query engine. A wrapper SPA
  provides a file tree, an inspect panel, and its own theme toggle.

---

## Strengths

1. **A real semantic layer, done right.** Metrics are defined once and reused everywhere:
   our run-only pace (`Σdist/Σtime where sport='run'`), time-weighted stride length, and
   aerobic efficiency each live in one place and feed KPIs, trends, and scatters alike.
   This is the LookML/dbt-metrics idea in a lightweight, local form — the core reason to
   choose anfra over raw chart libraries.
2. **Everything is code, git-first.** Models, queries, and apps are text: reviewable,
   diffable, revertible. `anfra validate` is a clean CI gate. No drag-and-drop state to
   export/import; no vendor lock on your definitions.
3. **AQL is genuinely expressive.** Query-local derived dimensions (`dimension b = case(when:
   ..., then: ...)`), date-semantics filters (`matches @(last 90 days)`), semi-additive
   KPI patterns (`metric x = t.ctl | where(t.week == max(t.week))`), and cross-model
   relationships via datasets. We never hit a wall that forced us into raw SQL views.
4. **Headless-testable end to end.** Every query runs through the CLI against real data —
   we verified all 21 app queries in a loop before touching the browser. Charts can be
   exercised in Node with ECharts SSR + stubs (see harness notes below). This is rare and
   valuable; most dashboard tools are browser-debug-only.
5. **Zero-infra data sources.** Pointing at a DuckDB file took 4 lines of YAML and no
   credentials. For personal/team analytics on local files this is the lowest-friction
   path we've seen.
6. **Total presentation freedom.** Full custom typography, a Hokusai palette, light/dark
   theming, custom controls, donut-click cross-filtering — the app is just HTML/CSS/JS.
   No chart-type ceiling, no theme fighting a walled garden.
7. **Fast local loop.** `anfra serve` auto-reloads on file changes; the app is a single
   HTML file with no build step.
8. **Cross-filtering and controls are declarative but not limiting.** One date control
   maps grain-natively to different columns per query (`activities.date`,
   `weekly_summary.week_start`, ...); multiselects map to activities-grain queries only;
   a donut slice click filters eight other charts. The model handles the plumbing.

---

## Weaknesses

1. **Young software, thin docs.** The bundled skills/references are essential (guessing
   AML syntax fails); `anfra skills install` was broken (CLI flag error) so we read them
   from the repo. Expect cryptic validate errors for missing required properties.
2. **The runtime iframe is a hard boundary.** Apps are sandboxed (`allow-scripts`, opaque
   origin, `srcdoc`): the wrapper's day/night toggle cannot reach the app's document, and
   `localStorage` throws. Theming, persistence, and any parent communication must be
   solved inside the app (we shipped an in-app toggle; OS preference works via
   `prefers-color-scheme`).
3. **Embedded engine lag.** anfra's query sidecar embeds an older DuckDB that cannot read
   files written by the DuckDB 2.x CLI's new default storage format — every query fails
   with an opaque `initialize driver: internal error`. Files must be written in
   `STORAGE_VERSION 'v0.10.0'`.
4. **The server holds the database lock.** While `anfra serve` runs, the DuckDB CLI and
   anything else can't open the file; any data rebuild requires a server restart. Fine
   for a personal tool, annoying in a rebuild-heavy loop.
5. **No charts included.** You assemble ECharts (or anything) yourself: number/string
   coercion from the SDK, null handling, palettes, per-chart render states (loading /
   error / empty / chart). It's ~60 lines of shared boilerplate before chart #1. Power
   for developers; a wall for non-programmers.
6. **Library-version landmines surface as generic errors.** One echarts 6.1.0 piecewise
   `visualMap` crashed with `d[0].coord` and took down every chart after it in the render
   pass ("Couldn't load this chart"). Root-causing required a headless reproduction.
7. **Apps grow monolithic.** One HTML file with 21 charts is ~2.6k lines. No
   componentization, no partials; all layout/theming/JS in one document.
8. **It's a local personal/team tool, not a BI platform.** No auth/TLS deployment story,
   no scheduling/alerting, no exports, no row-level security, no visual explorer for
   ad-hoc slicing. Sharing = same machine, or host the page against your own engine.

---

## Issues encountered → solutions

| # | Issue | Root cause | Solution |
|---|-------|-----------|----------|
| 1 | All queries fail: `initialize driver: internal error` | DuckDB 2.x CLI wrote a new storage format the embedded engine can't read | Build DB via `EXPORT DATABASE` → `ATTACH ... (STORAGE_VERSION 'v0.10.0')` → `IMPORT DATABASE`; scripted in the sync pipeline |
| 2 | Charts fail at runtime: `d[0].coord` | echarts 6.1.0 piecewise `visualMap` bug (empty dimension in controller) | Replace visualMap with a two-series split (positive/negative TSB, null-gapped); NaN-guard any `Math.max(...vals)` feeding `visualMap.max` |
| 3 | Dashboard stuck in night mode | App renders in a sandboxed iframe; the frame's `data-theme` toggle can't cross into it | In-app sun/moon toggle; priority chain `user choice → data-theme → prefers-color-scheme`; charts re-render via MutationObserver + matchMedia listener |
| 4 | CLI queries fail while server runs | canal-query sidecar holds the DuckDB file lock | Stop server for CLI/builder work; restart after every rebuild |
| 5 | `anfra validate` errors on Dataset | Required `data_source_name` and `relationships` (even empty); descriptions must be plain strings, not `@md` blocks | Follow the shipped examples verbatim; mirror connection files in a committed `.example` |
| 6 | Metric name collision (`ramp_rate` dimension vs metric) | AML namespaces collide between model dimensions and metrics | Rename metric (`weekly_ramp_rate`) |
| 7 | String PK broke joins | Some activity IDs are strings (`i51363809`) | Type id columns `text`, not number |
| 8 | Wrong numbers in charts | SDK delivers numbers as strings | `num()` coercion helper at every data boundary; verified with an SSR harness that also converts rows |
| 9 | AML/AQL syntax guessing fails | Docs-thin surface; grammar is opinionated | Read the bundled skills (`setup-repo`, `aml`, `write-aql`, `build-data-app`); copy their examples as the base |
| 10 | Browser-only debugging is slow | Errors surface as a generic per-query error state | Headless harness: extract `createQuery` AQL → run via `anfra query` → feed rows to ECharts SSR with DOM stubs → reproduce real crashes in CI-like fashion |

---

## Fit for the target audiences

### 1. Data / BI professionals replacing traditional dashboarding

**Strong fit, with eyes open.** The semantic layer + git workflow + headless query testing
is the part traditional tools do badly and anfra does well; the DuckDB/local-file path
makes personal analytics nearly zero-ops. The trade-offs vs an enterprise BI stack are
real: no scheduling/alerting/exports/RLS, no server deployment story, single-page apps,
and you own chart rendering. Choose it for developer-driven, code-reviewed analytics on
local or warehouse data where the audience consumes finished apps. Don't choose it (yet)
as a org-wide Tableau/Looker replacement — there's no governance, sharing, or explorer
layer.

### 2. Non-technical users building custom data apps

**Not yet, unassisted.** Even with declarative markup, building an app means: model your
tables in AML, write AQL metrics, then write real JavaScript with a charting library and
debug it in a browser console. There is no visual builder in this distribution. The
realistic pattern is a **pairing model**: a technical person seeds models/datasets and a
styled app template; non-technical users then consume the app (which is genuinely good —
one URL, friendly filters, cross-filtering) and request metric changes as one-line AQL
edits. If holistics ships a visual app builder or template gallery, this audience opens
up; today the framework is a developer tool that produces excellent apps *for*
non-developers.

---

## Patterns worth keeping (regardless of tool)

- **Derived columns beat query-local cases for reusable splits** (e.g. `run_surface`
  computed at load: road/trail/indoor), while query-local `case()` is perfect for
  bucketing used once (pace blocks).
- **Weight averages with a time column** (`Σ stride·moving_time / Σ moving_time`), and
  guard the input (`cadence > 40`) against walk-break pollution.
- **Semi-additive KPIs** (latest CTL/ATL/TSB) via `where(week == max(week))` inside the
  metric, not the chart.
- **HR decoupling** = `(r1 − r2)/r1 · 100` on time-halves of `Σspeed·dt / Σhr·dt`;
  positive = drift. Expect outliers from strides/surges — keep them visible, note them.
- **Storage-version discipline** when a file DB is consumed by an embedded engine.
- **Verify queries headlessly, render charts headlessly**; reserve the browser for
  interaction testing only.

---

## Verdict

anfra is the best-in-class example so far of "semantic layer + code-first local data
apps": high ceiling, real software-engineering ergonomics, zero-infra data sources. Its
costs are the costs of youth: thin docs, an iframe runtime with sharp edges, an embedded
engine pinned to older file formats, and a fully DIY presentation layer. For BI
professionals it's a compelling daily driver for personal/team analytics; for
non-technical builders it needs a technical enabler in front of it.
