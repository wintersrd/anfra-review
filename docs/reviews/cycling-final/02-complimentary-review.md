# Complimentary review — where the Streamlit solution is superior (v2, skill-built build)

Scope and stance mirror `01-adversarial-review.md` (v2 supersession, three
perspectives, port incidents excluded). This file lists only what is
*better* in the Streamlit build.

The headline of v2: **the skill closed the fidelity gap that separated
the two builds, and the verification discipline widened its lead.** The
v1 review conceded their process beat ours; v2 confirms it with stronger
machinery, on top of a data layer that now gets the numbers right.

---

## A. Data team / platform owner

### A1. A continuous, self-pinning numeric contract — now with constants

v2 strengthens the v1 equivalence idea into a three-way contract:
- 43 equivalence tests (10 typed functions × default/empty/narrowed
  windows, 8 plain × default/empty, KPI splits, K1);
- 27 oracle tests with pinned fingerprints (K2 29.7026 km, K3 5665 m /
  498.6 km, K4 0.7591 / 10 rides — reconciling exactly with our
  independently-built app: two codebases, one warehouse, same numbers);
- **`test_constants_pinned_between_layers`** — the 10 shared constants
  (zone edges/labels, cadence buckets, guards, long-ride threshold) are
  asserted equal across oracle and live layers, so the buckets can no
  longer drift between "what the test checked" and "what the app drew".

Our build's numeric verification remains one-time and interactive
(WORKLOG reconciliations), plus structural gates (22-query execution,
SSR render, fingerprints). Nothing we ship fails if a metric's *value*
changes semantics tomorrow. Their suite is what the platform should
template.

### A2. The gates caught real, subtle bugs during bring-up — evidence they work

Not hypothetical discipline; the WORKLOG records what the oracle +
equivalence loop surfaced: `km or 0` doesn't catch pandas NaN (NaN is
truthy → K2 mean went NaN); `date_bounds()` returned Timestamps whose
`isoformat()` carried `T00:00:00`, skewing window edges (a 13-vs-14-week
ramp discrepancy); SUM-over-no-rows NULL vs 0 semantics diverged between
layers (fixed with `COALESCE`, oracle-side); the bare `AnfraClient()`
constructor ignores `ANFRA_MCP_URL` (fixed with `from_env()`). Every one
of these is a *class* of bug our HTML path can only find in a browser.

### A3. Warehouse-reproducible derivations

v2 moves §8.5's weight carry-forward into the warehouse as a build-time
`weight_ref_kg` column — resolvable for 155/155 rides, testable in SQL,
reusable by any future consumer. Ours computes carry-forward in page
JavaScript at render time: invisible to SQL consumers, untestable except
via the render harness. Their choice changes the warehouse (a
reconciliation cost — see the adversarial review) but the direction —
*if a derivation matters, make it data, not view* — is right, and their
own skill's "no view-layer math" rule is the codified lesson.

### A4. An interpretation-decision register as a first-class artifact

Numbered decisions D1–D14, each tagged (B)uilder or owner, each
recorded *before* implementation (bucket edges, EBike mapping, K2
zero-week semantics, wall-clock vs data-relative defaults, §8.5
aggregation). Our WORKLOG records decisions too, but theirs is
structured per the skill's step 0 — which is precisely what made the
v1→v2 comparison auditable and what makes the two builds' divergences
(e-bike, buckets) tractable to reconcile rather than surprising.

### A5. Engineering hygiene, verified honestly

88.72% coverage with 300 passed / 0 skipped; mypy clean on the four
cycling files, with the *pre-existing* repo-wide conftest duplicate
verified (stash → reproduce at parent commit → restore) before being
declared not-theirs; ruff catching a mixed-case constant typo and an
invalid format spec; one red commit caught and fixed in-push, logged
without hedging. The app layer being deliberately `Any`-typed is stated
up front rather than hidden.

---

## B. Analyst / data scientist

*(new perspective; extended in `04-simulation-apps-analysis.md`)*

### B1. The full Python ecosystem, one import away

The v2 data layers are plain typed Python over `anfra_client` — which
means the analyst ceiling is the ecosystem: pandas/numpy/scipy now,
models and simulation later (the race-planners pattern: pure core +
tests + thin UI). The sandboxed HTML tier structurally cannot follow an
analyst past rendering; this tier can become the analysis itself.

### B2. A governed SQL scratchpad — an actual analyst workflow, demonstrated

The oracle is not just a test twin; it is a place to *hypothesize in
SQL, pin the fingerprint, then lift to AQL and let equivalence prove the
lift*. v2 demonstrates the full loop 22 times over. For an analyst, that
converts "the semantic layer constrains me" into "the semantic layer
catches my translation errors" — the right polarity, and something our
path offers no equivalent of (our AQL lives in HTML; there is no SQL
twin to think in).

### B3. An importable, typed function catalog

`from streamlit_app.cycling_queries_aql import power_zones_weekly` —
notebooks, batch jobs, and future apps consume the same 22 functions the
app renders, with the same guards and buckets. Our app's data surface is
22 AQL template literals inside an HTML file: extractable by regex for
tests, importable by nothing.

### B4. Reproducibility hooks built in

`today` is an injectable parameter on every wall-clock function;
`CYCLING_DB` redirects the oracle at a fixture; the AppTest seeds a
cross-filter and clicks Clear. Analyses become re-runnable as-code —
cheap now, and the habit that simulation-grade work (parameter
snapshots, as-of semantics; `04` §5) will demand later.

### B5. Subtle-data-plumbing hygiene is analysis hygiene

NaN truthiness, Timestamp serialization skewing window edges, NULL-vs-0
aggregation semantics — these are exactly the failure modes that ruin
quiet analyses. Their gates caught all three during bring-up; most
dashboard stacks (ours included) would have shipped all three.

---

## C. Non-technical stakeholder / app-builder

### C1. The skill productized their loop too

v2's build followed the skill's contract — declaration table, numbered
interpretation decisions, two-file data layer, four-state cells, load
log, AppTest gates — and the resulting README hands the stakeholder a
*change-request vocabulary* (load-log keys) plus a documented run
command. The v1 gap ("no productized loop") is closed on their side;
what remains is the Python fluency tax (adversarial C1), which no skill
removes.

### C2. Native widgets, session persistence, free interactivity

Accessible `st.radio`/`multiselect`/`date_input` maintained upstream;
`session_state` survives reruns (our filter state resets when the
sandboxed frame reloads — storage is forbidden there by design); Plotly
ships zoom/pan/box-select and selection events (`on_select="rerun"`)
with zero configuration. The sidebar multiselect even mirrors the donut
focus as a keyboard path — two affordances for one state.

### C3. Edit → rerun → *verified*

The stakeholder-facing difference that survived v1 untouched: their
iteration loop ends with "AppTest 4/4 green — zero exceptions, 23
load-log keys loaded, empty window friendly, cross-filter clears" — the
computer checking the whole app. Ours ends with "charts render in SSR;
please click around in the browser." The platform should treat their
gate as the spec for the anfra tier's missing tooling.

### C4. Graceful degradation as a tested behavior

`_run_query` fails a cell, logs it (rows = −1), renders `st.error`, and
the app survives — and the AppTest *asserts* the degraded paths
(empty-window rerun, virtual-only narrowing with friendly "—"). Our
four-state `renderStatus` implements the same discipline by hand; theirs
is enforced by a gate that reruns it on every change.

---

## Summary of the complimentary case (v2)

| Dimension | Streamlit v2 | Anfra build |
| --- | --- | --- |
| Numeric verification | 43 equivalence + 27 fingerprints + constants pinned, every run | one-time interactive reconciliation + structural gates |
| Full-app functional gate | AppTest 4/4 (default, empty, virtual-only, cross-filter + Clear) | SSR render only; user asked to browser-verify |
| Cross-build validation | headline KPIs reconcile with our independent build | same (mutual) |
| Derivations | carry-forward in warehouse (`weight_ref_kg`) | carry-forward in page JS (invisible to SQL) |
| Decision register | D1–D14, structured, per skill step 0 | WORKLOG decisions (unstructured) |
| Analyst ceiling | full Python; SQL scratchpad→AQL lift loop | rendering only |
| Reusable data surface | 22 importable typed functions | 22 AQL strings in HTML |
| Reproducibility | injectable `today`, fixture DB, seeded AppTest | none |
| Loop closure | edit → AppTest green | edit → SSR render → ask the user |
