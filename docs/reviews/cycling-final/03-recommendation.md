# Deployment recommendation — Anfra standalone vs Anfra backend + Streamlit

Inputs: `01-adversarial-review.md`, `02-complimentary-review.md`, both builds'
WORKLOGs and code, and this repo's own framework history
(`docs/anfra-framework-review.md`, which already road-tested the MCP →
Streamlit tier for the running dashboard). Hosting and infra are assumed
solved; the question is the **experience of building and managing apps**.

> **Addendum (see `04-simulation-apps-analysis.md`)**: this recommendation
> was derived from a dashboard build. Tested against a real simulation app
> (`race-planners`: 4,200 lines of Python domain core, 84 tests, GPX ingest,
> numpy/matplotlib, no warehouse), the tiering refines to three classes —
> (a) governed dashboards → anfra HTML; (b) warehouse-backed computational
> apps → anfra + Streamlit via the `anfra-streamlit-apps` skill; (c)
> simulation/modeling apps → Streamlit/Hex territory where the anfra HTML
> tier is architecturally out of scope (no libs, no file ingest, no
> persistence in the sandbox) and anfra's play is the data plane around the
> compute, not the compute. "Escape hatch" covers (b) only.

---

## What the head-to-head actually showed

Both builds, working the same spec in parallel, **converged on the same
architecture bottom**: a governed AML semantic layer queried through the
anfra backend. The Streamlit build even pivoted mid-flight to it (user
direction: *"core data layer should be built using the anfra backend and
data model… direct sql for validation only"*). That convergence is the
strongest signal in the whole exercise: **the semantic layer is not a
deployment option, it's the substrate.** The real choice is only about the
app tier that sits on top of it.

And on that choice, the two builds split the quality dimensions almost
perfectly:

- The **anfra-native app won on governance and fidelity**: it found and used
  the per-activity FTP the other build never saw; its metric math is
  denominator-consistent; its definitions live in the model and the page,
  nowhere else; it shipped with sandbox, SRI pins, structure markup, the
  Inspect panel, and block handles.
- The **Streamlit app won on verification and ergonomics**: a SQL-oracle
  equivalence suite re-pinning every number on each run, a full-app
  headless gate covering most of the acceptance criteria, typed and
  reviewed app code, and the entire Python/Plotly ecosystem for
  composition — plus native accessible widgets and free caching/state.

Neither dominance was caused by the tier itself. The Streamlit build's data
miss was reconnaissance, not framework; the anfra build's verification gap
is tooling, not architecture (the platform just doesn't have an AppTest
yet). But **tiers shape defaults**: the anfra path *makes* the governed
thing easy and the verified thing hard; the Streamlit path *makes* the
computed-and-verified thing easy and the governed thing forgettable (its
zone thresholds drifted back into Python within one build session).

---

## Recommendation

### 1. Deploy Anfra as the default, standalone app tier

For the population of apps this exercise represents — dashboards and
self-serve views over governed metrics — the anfra-native path should be
the standard:

- **For the data team**: definitions stay in the model; apps cannot fork
  them; every app is one reviewable file plus AML diffs; sandbox, SRI,
  structure markup, lineage, and the Inspect panel come for free; the
  `/apps/` list is the portfolio. The adversarial review's worst findings
  (runtime-defined zone thresholds, mixed-denominator metrics, the 240 W
  constant presented as truth) are all things that happen *when apps own
  definitions* — the anfra tier structurally prevents them.
- **For the non-technical builder**: it is the only path with a
  productized loop — design agreement, declaration list, reference docs,
  a single artifact the platform lists, serves, live-reloads, and lets
  them hand back block handles from the Inspect panel. The Streamlit path
  required Python fluency, a package environment, a second process, and
  env-var plumbing before the first chart rendered.

### 2. Sanction Anfra-backend + Streamlit as a governed escape hatch, not a peer default

Keep the tier this repo already proved (running dashboard, now the cycling
app): the semantic layer via `anfra_client`/MCP underneath, Streamlit for
what it is genuinely best at. Use it when:

- the artifact is **computational** — pandas/numpy/stats/ML, exploratory
  analysis, anything the sandbox can't express;
- the builder's fluency **is Python** and the alternative is no app at all;
- the app needs framework-maintained accessible widgets or Plotly-class
  interactivity today.

But manage it as a second-class-but-supported tier with explicit
obligations, because the costs are real and were demonstrated:

- definitions live in AML, never in app code — their runtime
  `_zone_case()` interpolation is the anti-pattern to lint against;
- **every metric lands in the model through platform review before an app
  uses it** (this is what would have caught the mixed-denominator
  `cycle_np_w`/`cycle_cadence_rpm` and the missing `icu_ftp`);
- Streamlit apps accept they don't get the sandbox, the structure panel,
  block handles, or platform theming, and they don't appear in `/apps/`.

Do **not** let Streamlit become the default app tier. The moment it does,
the platform's guarantees (fidelity, governance, discoverability) become
optional conventions, and the parallel-build outcome here previews the
steady state: two metric families (`cycle_*` vs `cycling_*`), a divergent
denominator convention, and definitions smeared across three layers.

### 3. Regardless of tier choice, adopt the Streamlit build's two disciplines platform-wide

These are the actual lessons of the head-to-head, and both are portable
into the anfra tier:

1. **Oracle equivalence suites for every new metric family.** A 20-case
   AQL↔SQL suite is cheap, and it is the only automated thing that pins
   *numbers* rather than *execution*. The anfra build should have shipped
   one; the platform should template it (`anfra` could even generate the
   SQL twin from compiled AQL as a starting point).
2. **A full-app headless gate (an "AppTest for anfra apps").** The node
   chart harness in `tests/anfra/` is 70% of one — it already stubs the
   SDK and executes the real page script. Extending it to drive the
   stubbed controls (set a filter condition, click the donut handler,
   assert the banner and the empty states) would close the biggest gap
   the comparison exposed, and would have let the anfra build end with
   "the app is verified" instead of "please check six things in your
   browser."

### 4. Housekeeping this comparison surfaced (do before merging either branch)

Reconcile the two semantic-layer extensions under one owner: one metric
family (`cycle_*` vs `cycling_*` — pick names once), one decoupling
dimension (`hr_decoupling` vs `decoupling`), `work_kj` in or consciously
out, consistent weighted-metric denominators, and `ftp_ref` (per-activity
FTP) as the single §8.1 source. That reconciliation is a ~30-minute
platform decision now, or a permanent divergence between two dashboards
later.

---

## Addendum — the BI-tool-first portfolio (and the vendor's own positioning)

A further challenge from the owner: *if BI-type tasks should belong in a BI
tool, and complex apps can be built elsewhere (Streamlit/Python), does that
change the analysis and recommendation?* Context: anfra's current website
(FAQ) has dropped its Hex/Streamlit comparisons and now pitches the BI
adjacency explicitly — *"run anfra next to your current tool and use it for
the reports your BI tool doesn't handle well, such as custom funnels, cohort
views or apps that combine analytics with your team's workflow."*

### The portfolio answer

The opinion doesn't break the analysis — it resolves the market into the
vendor's own current positioning, and the two builds slot into it cleanly:

| Tier | Gets | Why | Evidence in this exercise |
| --- | --- | --- | --- |
| BI tool | Standard reporting: fixed chart types, filters, layouts | Self-service authoring by analysts, distribution, alerting, RLS, usage telemetry — none of which either alternative provides | (Absent by framing — this org has no BI tool; both builds were agent-built code) |
| **anfra HTML tier** | The **BI-overflow class**: apps a fixed chart vocabulary can't express and software engineering shouldn't absorb — custom interactions, spec-exact formatting/empty-state contracts, analytics embedded in a workflow | Fidelity + governance + productized agent loop; every number traceable to a reviewed metric | The cycling app: its spec (cross-filter choreography with exclusions, per-component empty states, exact formats, K2's complete-week definition) is a *software spec*, and that is precisely the class a BI tool fights |
| anfra semantic layer (AML/MCP) | Substrate for every custom tier, including the Python one | Metrics defined once, compiled to readable SQL, lineage, reviewable diffs | Both builds converged on it independently; the Streamlit build was redirected to it mid-flight |
| Streamlit / Python (on the semantic layer) | Complex, computational, simulation apps — including the (c-priv) parameterized simulator (`04` §5) | Ecosystem, tests-over-the-core, compute the sandbox cannot host | race-planners; the sibling build's verification discipline |

### What changes in the recommendation

- **Re-scope one phrase.** "Anfra standalone is the deployment default" was
  framed against Streamlit. Under the BI-tool-first opinion it becomes:
  *anfra is the default tier for **custom governed apps** — the overflow a
  BI tool can't express — not for reporting generally.* Standard reporting
  belongs to the BI tool; that was never anfra's claim (per the FAQ) and
  shouldn't be ours.
- **The honest caveat cuts both ways.** anfra's app tier is
  agent-mediated: every app and every change is a reviewed code change. A
  BI tool gives an analyst population drag-drop self-service. If the
  dashboard backlog is broad and standard, the BI tool wins on cost per
  dashboard and anfra's wedge narrows — further still if the incumbent BI
  tool already owns a strong semantic layer (Looker/LookML), which would
  make anfra's substrate redundant rather than foundational. anfra's
  strongest org-fit is the team whose BI tool has a weak or absent
  semantic layer and whose custom-app backlog is engineering-starved.
- **Everything else survives untouched**, because none of it depended on
  where BI tasks live: the semantic layer as substrate for whatever custom
  apps get built (including Python ones), definitions in AML under review,
  the two disciplines to adopt platform-wide (oracle equivalence,
  full-app gating), the (c-priv) data→application seam, and the merge
  housekeeping. The vendor's FAQ pivot away from Hex/Streamlit implicitly
  concedes the race-planner class — consistent with `04`'s (c-pub)
  conclusion; the (c-priv) parameter-plane play remains our extrapolation,
  not their claim.

### Bottom line (restated for the portfolio)

Three-way split: **BI tool for standard reporting; anfra for the governed
custom-app tier between BI and engineering; Python (on the anfra semantic
layer) for computational and simulation apps.** Deploying anfra does not
mean retiring the BI tool or the Python stack — it means the custom-app gap
between them stops being either a BI-tool fight or an engineering ticket,
and every custom app, whatever its tier, reads its numbers from the same
reviewed definitions.

---

## Final correction — the Holistics context (anfra's origin)

Last material fact, supplied by the owner: **anfra is produced by
Holistics** — a BI company whose platform is built on a programmable
semantic layer (AML) and AQL, i.e. the exact modeling language this repo
uses (the `.aml` syntax on holistics.io is the same `Model { dimension …
measure { definition: @aql … } }` / `Dataset { models: […] relationship(…) }`
we edited). Holistics already ships, per its site: self-service BI with
drill-down/through, **custom charting via Vega-Lite**, embedded analytics,
governance (RLS/SSO/audit), analytics-as-code (models, metrics *and
dashboards* in Git with PR review) — and, decisively:

- **Agentic dashboard creation in the platform**: "Point Claude Code,
  Codex, or Cursor at your BI codebase. Or use our in-browser Development
  Copilot to build models, metrics, and dashboards" — plus AI blocks that
  write findings onto dashboards and conversational analysis that saves to
  dashboards.
- **Semantic-layer access for external tools**: "Query your metrics from
  Claude, ChatGPT, Cursor, or your own app **over MCP and APIs**. Every
  tool reads the same definitions."

The owner's team position follows from this: *the BI/data-viz case is best
served by enriching Holistics' AI/agentic capabilities; for actual data
apps (the notebook/Streamlit class), anfra-as-builder does not suffice —
but access to the semantic layer would enormously improve them.*

### What this does to the recommendation

1. **Class (a) in a Holistics org: the anfra HTML tier's wedge largely
   collapses into Holistics itself.** My previous addendum warned the wedge
   narrows "if the incumbent BI tool already owns a strong semantic layer";
   with Holistics the incumbent doesn't merely *have* the substrate — it is
   the substrate's origin, and it adds the two things the HTML tier was
   holding the fort for: custom viz (Vega-Lite) and agentic authoring
   (coding agents on the BI codebase, in-browser copilot). A Holistics
   customer gets the governed-dashboard outcome — definitions once, agent
   speed, review-as-code — without a second app tier. The HTML tier's
   residual value in such an org: artifacts that exceed dashboard semantics
   outright (workflow-embedded apps with arbitrary interaction
   choreography, not fancier charts), and the fact that its agentic loop
   works today end-to-end (the skill → sandbox → Inspect chain this
   exercise validated) while in-platform agentic creation matures. For
   orgs *without* a BI platform, anfra remains a credible OSS stand-alone.
2. **For data apps, the owner's position is what the head-to-head actually
   demonstrated.** The sibling Streamlit build's failures were all
   definitional — the 240 W constant, mixed denominators, runtime zone
   thresholds — and all are cured by building on the semantic layer, which
   both Holistics (MCP/API) and anfra (local MCP server, as `anfra_client`
   consumed here) expose. Its strengths — oracle equivalence, full-app
   AppTest, typed compute — are Python-native and unreachable from any
   sandboxed app tier. So: build the app in Python; get every number from
   AML over MCP; keep definitions in the model under review. The
   `anfra-streamlit-apps` skill plus the two platform disciplines
   (oracle-equivalence suites, full-app gates) are the operational form of
   that rule, and `04` §5 is its extension to simulation apps
   (athlete-grain parameters, snapshots, write-back).
3. **The two-experiment synthesis, finally stated in one line each:**
   the cycling head-to-head measured *what the semantic layer contributes
   to an app* (fidelity, governance, one source of truth — enormous), and
   *what the app tier contributes* (the HTML sandbox's governance surfaces
   and productized agent loop vs Python's verification ergonomics and
   compute — each real, each secondary to the substrate).

### Final recommendation (Holistics-org form)

- **BI/dashboard class → Holistics**, with investment in its agentic
  creation and AI surfaces; treat anfra HTML apps as the interim/edge
  option (no BI platform, or app-choreography beyond dashboard semantics).
- **Data-app class → Python (Streamlit/notebooks) on the semantic layer**
  via MCP — anfra's local OSS server or Holistics' APIs — with the
  obligations that make the bridge safe: definitions in AML never app
  code, metric changes through model review, oracle-equivalence and
  full-app gates as standard CI.
- **Unchanged regardless of tier**: the semantic layer is the substrate;
  the verification disciplines are the quality bar; the (c-priv)
  data→application seam is the design pattern for internal simulation
  apps; and the `cycle_*`/`cycling_*` reconciliation still needs one
  owner before merge.

## v2 re-review — the skill-built Streamlit build (the A/B result)

The owner rebuilt the Streamlit app from the same spec using the refined
`anfra-streamlit-apps` skill (`~/repositories/cycling-streamlit`, branch
`cycling-streamlit`). That makes this exercise a rare controlled
comparison: **same builder ecosystem, same spec, same warehouse — one
variable changed, the skill.** Reviews `01`/`02` are rewritten against
it; this section updates the recommendation. (Perspectives now three:
data team, analyst/data scientist, non-technical stakeholder.)

### What the A/B showed

1. **The skill closed the fidelity gap.** v1's worst finding (240 W
   configured constant; `icu_ftp` never found) is gone — the skill's
   mandatory raw-payload interrogation step caught the column ("exactly
   the skill's recorded trap"), `ftp_ref` landed in sync + AML, and the
   headline KPIs now **reconcile exactly with our independent build**
   (K1 250 W; K2 29.7026 vs 29.70; K3, K4, C10-speed identical). Two
   codebases, one warehouse, same numbers — the strongest validation
   either build got.
2. **The skill strengthened the gates.** 43 equivalence tests + 27
   pinned fingerprints + a constants-pinned-between-layers test + an
   AppTest that now covers the cross-filter pre-seed and Clear click —
   on top of 88.72% coverage and mypy-clean data layers.
3. **But the counter-example also landed: prose rules don't govern
   models.** The skill's same-column denominator rule exists — and the
   v2 AML `ride_*` metrics still weight by moving while dividing by
   elapsed, because the rule lives in the layer-parity section and
   AML-dataset authoring never passed under it. The oracle shares the
   convention, so 43 green equivalence tests pin the slip in place:
   parity, not truth. And our own build carries the mirror bug
   (metric descriptions saying "moving" over elapsed-time formulas) —
   caught by nobody, because nothing reads descriptions. The missing
   piece in **both** paths is the same: a model-review step where
   conventions (moving vs elapsed, e-bike mapping, bucket edges) are
   decided once, written into metric definitions, and diffed.

### Updated recommendation

The two options in the brief are now much closer than v1 suggested, and
the choice stops being about quality control (the skill supplies that in
both directions) and becomes about **tier properties and audience**:

- **Anfra standalone (HTML Data App tier)** — for governed dashboards
  and custom metric-consumption apps: platform governance surfaces
  (sandbox, SRI, structure, Inspect, `/apps/`, live reload), no runtime
  or fluency tax beyond reading AQL/AML, and definitions that cannot
  leak into app code (there is nowhere to put them). In a Holistics
  org, this wedge largely belongs to the platform itself (see the
  Holistics section above); anfra HTML stands in where there is no BI
  platform or the artifact exceeds dashboard semantics.
- **Anfra backend + Streamlit (the skill tier)** — now a **credible
  first-class tier, not merely an escape hatch**, for Python-fluent
  builders and analysis-grade apps. Its obligations stand and are
  demonstrably enforceable: definitions in AML under model review,
  metric changes through AML diffs, oracle-equivalence + full-app gates
  as CI. It remains the only tier that reaches the analyst/data
  scientist audience (compute headroom, SQL-scratchpad→AQL lift loop,
  importable typed catalog, reproducibility hooks — `02` §B) and the
  only architecture for simulation-class work (`04`).

**Platform moves the A/B argues for** (updating §3 of the original
recommendation): (i) absorb the oracle-equivalence and AppTest gates as
productized platform features — they are the proven quality delta in
both directions; (ii) extend the skill's authoring rules into the AML
step, and have metric *descriptions* generated or pinned from the same
convention as formulas (our own doc-drift is the proof they rot
independently); (iii) a **conventions register** in the repo (one named
`t` per family, enum mappings, bucket edges) that both the skill and
model review treat as the single decision point.

**Housekeeping, updated (do before merging either branch):** the
reconciliation list grew — `ride_*` vs `cycling_*` families; EBikeRide →
road (their D3) vs NULL (ours), i.e. road 35 vs 34; C12 bucket edges
`<70…` vs `<60…`; §8.5 as warehouse `weight_ref_kg` column vs page-JS
carry-forward (prefer theirs — reproducible; `02` A3); elapsed-vs-moving
conventions in both directions including our description fixes; their
build-time `COALESCE` ftp_ref vs our pure alias (prefer ours — preserves
provenance and case-3). One owner, one afternoon, one warehouse dialect
afterwards — or two dashboards that disagree by design.

## Bottom line

**Anfra standalone is the deployment default; Anfra-backend + Streamlit is
a sanctioned, obligations-bearing escape hatch for computational apps.**
The comparison says the semantic layer earned its place as the substrate
(both builds chose it), the anfra app tier earned the mainstream (fidelity,
governance, productized builder loop), and the Streamlit tier earned its
niche (ecosystem, verification ergonomics, computational headroom) — while
also supplying the two disciplines (oracle equivalence, full-app gating)
that the anfra platform should absorb as first-class features.
