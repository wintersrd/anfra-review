# Adversarial review — where the Streamlit solution is inferior (v2, skill-built build)

Scope: the **second** Streamlit build at `~/repositories/cycling-streamlit`
(branch `cycling-streamlit`, 8 commits, built with the refined
`anfra-streamlit-apps` skill), vs this repo's anfra-native build
(`apps/cycling.html`). This file **supersedes v1** (in git history): the
v1 build's headline defect — FTP = 240 W configured constant, missing
`icu_ftp` — is **fixed** here (found during the skill's mandatory
raw-payload interrogation; `ftp_ref` = COALESCE(icu_ftp, env constant);
K1 = 250 W measured, matching our build; headline KPIs now reconcile
across builds: K2 29.7026 vs our 29.70, K3 5665 m / 498.6 km and K4
0.7591 / 10 rides identical, C10 road 27.79 km/h identical).

Port-collision incidents are excluded per the brief. Three perspectives,
per the brief: data team/platform owner, analyst/data scientist, and
non-technical stakeholder. This file lists only what is *worse* in the
Streamlit build; `02-complimentary-review.md` is the reverse. Honest
counter-findings against **our own** build are marked ⟂.

---

## A. Data team / platform owner

### A1. The mixed-denominator defect survived the skill — in the AML itself

The v1 finding (weight by `moving_time_s`, divide by `total_time_s`)
returns verbatim in the v2 **dataset metrics** (`ride_weighted_cadence`,
`ride_avg_watts`, `ride_w_per_kg`, `ride_intensity_factor`,
`ride_pct_ftp`: `Σ(x·moving_time_s) / total_time_s`). What it means:
the result is a *clock-time average* (work per elapsed second), not the
§8.x duration-weighted mean of ride values — numerator weights and
denominator sum are different `t`s. It is **invisible on this fixture**
(power rides are virtual, where moving = total; both builds' K4 agree to
four decimals) and **uncatchable by their gates** — the SQL oracle
mirrors the same convention, so 43 equivalence tests pin the slip in
place. Parity, not truth.

Why it matters for the platform owner: the refined skill **contains the
rule** ("weighted means weight and divide by the SAME column…") — but it
sits in the *layer-parity* section governing oracle/live query authoring,
and never governed **step-2 AML metric authoring**, where the defect
actually landed. Rules-as-prose reach the code an agent writes under
them; they do not reach the model unless model review happens. Our
build's weighted means are moving/moving consistent — with one honest
exception below.

⟂ **Our own build has the mirror-image bug**: `cycling_time_h` and
`cycling_speed_kmh` *describe* themselves as "moving hours" while their
*formulas* divide by `total_time_s`. Formula/description drift, caught by
nobody (extraction tests execute formulas; nothing reads descriptions).
Neither build is clean; both need one convention decision plus a
doc/formula fix — see A4.

### A2. Spec-fidelity gaps that persist from v1

- **Presets recompute data-relative, not wall-clock.** §6.2: the default
  window is data-relative, but a preset re-pick recalculates from the
  wall clock. Their `cycling_app.py` computes every preset range from
  `max_date` (latest ride): on this 11-day-stale fixture, re-picking
  "Last 90 days" yields 07-08 → 10-15 instead of 07-28 → 10-26. Logged
  in v1 as accepted debt (L6); silently unchanged in v2. Our build
  re-picks wall-clock.
- **FTP case-3 ("FTP not configured") is unreachable by design** (D5):
  `ftp_ref` = build-time `COALESCE(icu_ftp, 250)`, so the fallback is
  always live. Implemented and unit-tested, but the tile's provenance
  story can never occur — and the column silently blends one measured
  value fewer (154 icu_ftp + 1 assumed) with no marker in `ftp_ref`
  itself (recoverable only via the separate `icu_ftp` dim). Ours keeps
  `ftp_ref` a pure alias on `icu_ftp`: null when unmeasured, provenance
  preserved, case-3 reachable.

### A3. Tier-inherent governance surfaces, still absent

Unchanged by any skill: no sandbox with SRI-pinned assets; no structure
markup, no Inspect panel, no block handles; no `/apps/` listing or
platform live-reload; no lineage UI. Their load-log expander + README
"load-log keys" vocabulary is genuinely good app-level observability —
but it is per-app convention the platform cannot rely on or build on.

### A4. The merge debt is now bigger — it has spread to the warehouse

Two parallel builds extended the same sync script + AML incompatibly:

| Item | Their build | Our build |
| --- | --- | --- |
| Metric family | `ride_*` (12 metrics) | `cycling_*` (8 metrics) |
| EBikeRide (1 ride) | `ride_type='road'` (D3) | NULL / excluded |
| Road ride count | 35 | 34 |
| C12 cadence buckets | `<70, 70–80, 80–90, 90–100, 100+` (5) | `<60, 60–70, 70–80, 80–90, 90–100, ≥100` (6) |
| §8.5 weight reference | `weight_ref_kg` **build-time warehouse column** | computed in page JS from a weight query |
| §8.5 aggregation | per-ride W/kg, then duration-weighted (closer to spec letter) | weekly watts ÷ week weight |
| Weighted means | moving-weight ÷ elapsed-divide | moving/moving |
| Hours/speed denominator | total (elapsed), labeled "duration-based" | total (elapsed), mislabeled "moving" (⟂) |

Every row is a defensible interpretation of an ambiguous spec — that is
exactly the problem: **spec ambiguity resolved differently per build
belongs in one reviewed place**, and a second warehouse (their sync
script now emits `ftp_ref`/`weight_ref_kg` build columns) means the
reconciliation is a data-engineering task, not just an AML diff. Both
WORKLOGs make the divergence *findable*; neither prevents it.

### A5. Process wobbles, honestly logged but real

One commit landed red (`pytest | tail` hid a failing assert — oracle
power-week pin 7 vs 6), fixed as a fixup in the same push; the app layer
is deliberately `Any`-typed ("matching app.py style"), so strict typing
covers the data layers but not the 740-line UI module. Small, transparent,
and cheaper to fix than to hide — but a reminder that the gates are only
as good as the discipline of running them unfiltered.

---

## B. Analyst / data scientist

*(new perspective in the brief; extended analysis in
`04-simulation-apps-analysis.md`)*

### B1. The metric family straddles three homes

For an analyst consuming this work from a notebook: `ride_*` metrics live
in AML (queryable), zone edges and cadence buckets live as constants
pinned between two app-scoped Python files, and the §8.5 carry-forward
lives in a build-time column only their sync script emits. A third
consumer imports their app modules or re-derives. In the anfra-native
path the same critique applies to our page AQL (strings in HTML) — the
platform answer for both is the same: definitions belong in AML under
review, and the skill is one convention away from mandating it.

### B2. The AQL tax is real and they paid it

Their build hit and documented: `greatest(a, b)` inside a custom
dimension breaks the anfra_client renderer (comma parsing — worked around
with `case()`); live layer omits all-NULL rows while SQL keeps them
(needs normalization); SUM-over-no-rows is NULL in SQL vs 0 in the live
envelope (fixed by `COALESCE` on the oracle side). Every one is
survivable, and their docstrings record the mechanism — but an analyst
who thinks in SQL pays a translation cost at every step. (Our build pays
the same tax inside HTML — this is a platform gap, not a tier victory;
it belongs on the anfra roadmap, not in either app.)

### B3. Two of everything

The two-file data layer (oracle + live) with pinned constants is the
discipline that makes their numbers trustworthy — and it means every
analytic change is written twice, tested for equivalence, and pinned.
For a one-off hypothesis that is overhead; the honest analyst answer is
to prototype in the oracle and *stay* there — which silently abandons
the semantic layer. The equivalence leash makes that safe only if kept
attached; nothing structurally prevents an un-equivalenced SQL path from
becoming the real source of numbers.

---

## C. Non-technical stakeholder / app-builder

### C1. The fluency gate persists

The skill productized the *agent's* loop — but the artifact is still a
Python project: `uv`, a venv, two processes (serve + streamlit), env
vars (`ANFRA_MCP_URL`, `CYCLING_FTP_WATTS`, `CYCLING_DB`), port pinning,
and a reviewer who must read typed function signatures to check the
agent's work. Our path's reviewer reads AQL-in-HTML plus AML diffs.
Neither is "non-technical", but ours removes an entire runtime from the
picture, and the platform lists/serves/live-reloads the result.

### C2. Chrome and state limits that survived the rebuild

- Night mode is a session-state button that **always boots day**,
  ignoring the OS preference (ours follows `prefers-color-scheme`, the
  host frame's signal, and an in-app toggle).
- The preset radio still has no "Custom" state — manual date edits and
  the radio label disagree until a preset is re-picked.
- Framework chrome (e.g. `st.error` styling in night mode) remains the
  framework's, not the app's.

### C3. Handing work back and forth

Their README makes "load-log keys" the change-request vocabulary — good
discipline, but the key names a *data function*; ours names a page part
(`[Weekly power](data-anfra-block="weekly-watts")`) the platform's
Inspect panel can locate. For a stakeholder who does not read code,
naming a chart beats naming a function.

---

## Summary of the adversarial case (v2)

| Dimension | Streamlit v2 | Anfra build |
| --- | --- | --- |
| FTP data fidelity | ✅ fixed (icu_ftp found; 250 W; KPIs reconcile) | 250 W, per-activity (case-3 reachable) |
| Weighted-metric math | mixed moving/elapsed in AML `ride_*` (latent on fixture) | moving/moving; ⟂ descriptions mislabel hours/speed |
| Preset semantics | data-relative re-pick (§6.2 deviation, silent in v2) | wall-clock re-pick |
| Definitions home | AML + app constants + build column (three homes) | AML + page AQL |
| Governance surfaces | none from platform | sandbox, SRI, structure, Inspect, `/apps/` |
| Merge debt | `ride_*` vs `cycling_*`, EBike, buckets, §8.5 mechanism, second warehouse dialect | same list, other side |
| Builder runtime | Python env, two processes, env vars | one HTML file |
| Theme boot | always day | OS + frame + toggle |
