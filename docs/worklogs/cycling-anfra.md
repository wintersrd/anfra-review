# WORKLOG — Cycling Data App (anfra-native build)

Branch `cycling-anfra` (this directory is already an isolated worktree for it;
`cycling-streamlit` is the parallel Streamlit build). Spec:
`docs/cycling-app-spec.md`. Skill: `build-data-app`. Quality gate: `anfra
validate` clean AND every embedded query executing against real data
(`tests/anfra/` pattern) + pre-commit.

## 2026-10-26 16:45 — Session 1 start: orientation

**Read (in order):** repo `AGENTS.md` (hard rules: DuckDB storage v0.10.0 via
sync script only; `anfra serve` holds the DuckDB lock; pre-commit ruff+unit;
conventional commits), `docs/cycling-app-spec.md` (C1–C17 + K1–K4, §8 metric
formulas), `build-data-app` skill + `references/api.md`, `references/example.html`,
`references/DESIGN.md`, `apps/running.html` (1439 lines — the parity bar),
models/dataset AML, `scripts/sync_intervals_icu.py`.

**Data state:** `data/running.duckdb` absent in this worktree at start; copied
`.env` + `running.duckdb` + `running_reader.duckdb` from
`~/repositories/running-analytics` (user-approved) at 16:43. Raw sync outputs
committed under `data/raw/` are the fixture source.

**Key findings:**

1. **The cycling model extension has NOT landed.** `activities.model.aml` has
   no `ride_type` / `ftp_ref`. Spec §2 marks them [extension] and says the
   extension is out of scope *of the spec document*, but the app cannot be
   built without them → this build lands the extension (AML + sync script),
   guided by the `aml` skill.
2. Raw NDJSON (`data/raw/activities.ndjson`, 1588 records, 1089 stubs) has
   per-activity `icu_ftp` on every real activity (rides: 154/155, values
   240→250 W over time, 4 distinct) → §8.1 case 1 (per-activity FTP) is
   implementable from real data; no build-time constant needed. But `icu_ftp`
   is NOT in `ACTIVITY_COLUMNS` → sync script + activities.csv need extending.
3. **Ride population:** 155 rides total (VirtualRide 106, Ride 34, MTB 13,
   Gravel 1, EBike 1), all 2024-10-05 → 2026-10-15 (athlete started cycling
   Oct 2024 — matches spec §3.3 "dense only from October 2024").
   Field density on rides: watts 86, cadence 122 (0–101 rpm), temp 47
   (15.6–36.0 °C), decoupling 84 (long rides ≥75 min: 36, of which 25 have
   decoupling), distance 67, elev 52. The 88 distance-less rides are HR-only
   indoor TrainerDay sessions (watch-recorded, no GPS/power) — spec §3.3
   "component analyzes only activities that have the required field" applies.
4. `weekly_by_category.category` label for cycling is **`Ride`** (not
   `cycling` as spec §3.2 loosely says) — adapt + document.
5. Weekly weight: 293/772 weeks, first 2012-10-08, **last 2026-01-05** → W/kg
   carry-forward (§8.5) genuinely matters for 2026 rides.
6. The single EBikeRide (`i100407075`, "Telgruc-sur-Mer eBiking", leisure,
   no power/cadence/FTP, 14.6 km, 10.5 km/h avg) needs a ride_type mapping
   decision → asked user (recommended: leave NULL = excluded, matching the
   run_surface CASE precedent of mapping only canonical types).
7. `anfra status`: not running. Tests exist for running.html's 21 embedded
   queries (`tests/anfra/test_anfra_queries.py` via `extract_aql`) — cycling
   build adds a parallel module.
8. Repo branches: `main`, `cycling-anfra` (this worktree), `cycling-streamlit`
   (other worktree). On `cycling-anfra` already → Worktree-first rule satisfied.

**Spec gaps found (to raise with user in design agreement):**

- C12 cadence buckets: spec points at §8.6 but §8.6 is Hilliness — no cadence
  bucket edges are defined anywhere. Proposing <60 / 60–70 / 70–80 / 80–90 /
  90–100 / ≥100 rpm (left-inclusive, mirrors %FTP bucket style).
- KPI windows: K2/K3/K4 define exact wall-clock windows ("this definition is
  exact") → plan: KPI tiles honor ride-type filter + cross-filter but NOT the
  global date-range filter; date-range still applies to C1–C17 per §6.1.
- C1 "from earliest available week to window end" → full history to `to`
  (planned mechanism: a `before`-only date filter for C1's week cap).

**Next:** design-agreement questions to user (look, cadence buckets, EBike
mapping, declaration list), then model extension → DB rebuild → queries →
app → gates.

## 2026-10-26 16:52 — Design agreement (user decisions)

Presented the read-back + 22-query declaration list. User approved all four
recommendations:

1. **Look:** Great Wave palette, same as `apps/running.html` (parity bar).
2. **Cadence buckets (C12):** `<60, 60–70, 70–80, 80–90, 90–100, ≥100 rpm`,
   left-inclusive — closes the spec gap (spec's §8.6 pointer was wrong).
3. **EBikeRide:** leave `ride_type` NULL → excluded from the app (matches
   `run_surface` precedent); 154 of 155 rides analyzed.
4. **Declaration list:** approved as listed (22 queries, controls/mappings,
   model extension, gates).

Implementation order from here: sync-script extension → offline CSV regen →
DB rebuild (v0.10.0 via script) → AML extension → `anfra validate` → draft +
run every query via `anfra query` → write `apps/cycling.html` → test gates →
pre-commit/commits.

## 2026-10-26 17:2x — Semantic layer extension + all 22 queries verified

**AML landed (validate clean):**

- `activities.model.aml`: `ride_type` (text, visible; road/virtual/mtb/gravel,
  null = not a typed ride), `ftp_ref` (number, hidden, → `icu_ftp`),
  `decoupling` (number, hidden, sign-preserved intervals.icu value).
- `running_analytics.dataset.aml`: `cycling_*` metric family (activities,
  distance_km, time_h, elev_gain_m, weighted_watts (t-weighted), if
  (t-weighted watts/ftp), avg_cadence (t-weighted, >40 guard), speed_kmh
  (Σkm/Σh), elev_per_km (hilliness)) — all guarded `ride_type is not null`
  (+ null-field guards so HR-only rides never dilute denominators); new
  `cycling` view group.
- `.anfra/data_sources.yml` recreated (git-ignored; worktree lacked it) →
  points at THIS worktree's rebuilt `data/running.duckdb` (the sibling repo's
  DB lacks ride_type/icu_ftp columns — local path is load-bearing).

**Query-phase findings (all 22 queries run via `anfra query`, sequential only —
parallel CLI calls contend on the DuckDB lock):**

1. **`max_by(table, value, by)` works, chained semi-additive doesn't.**
   K1's "FTP of latest ride that has one":
   `max(ftp_ref) | where(ftp_ref is not null) | where(date == max(date))`
   returned NULL (the inner `max(date)` lifts to the UNFILTERED table —
   latest overall activity is a run, no ride that day has ftp). Fixed with
   `activities | max_by(activities.ftp_ref, activities.date) | where(ftp_ref
   is not null)` → 250 W ✓ (SQL-verified).
2. **Natural time expressions:** `@(this week)` is Monday-aligned (ISO) ✓;
   `@(last 4 weeks)` / `@(4 weeks ago - last week)` are DAY arithmetic
   (trailing 28×24h, [Mon−28, Mon) only when today IS Monday). Spec K2 needs
   the 4 preceding COMPLETE ISO weeks on any weekday → **K2 query returns
   week-grain rows** (`week_start >= @(5 weeks ago)`, verified ≥ needed
   coverage on any weekday) and **JS slices** currentMonday + the 4 prior
   Mondays exactly. Reconciliation check: AQL single-number 118.81 km / 4 =
   29.70 = mean of the four weekly rows ✓.
3. **Wall-clock 90d KPIs:** `matches @(last 90 days)` = [today−90, today]
   window. SQL cross-check on a data-relative window differs in elev/km
   (5665 m/498.6 km wall-clock vs 5849/520.6 data-relative) — spec §K3/K4 say
   *wall-clock*, so the AQL numbers stand; IF identical both ways (0.759078,
   10 power rides).
4. CASE query-local dimensions work (`ftp_zone`, `cadence_bucket`,
   `temp_bucket_c` incl. floor() arithmetic and negative clamp).
5. Empty aggregates return `null` (not 0) → JS renders 0.0 / gaps.
6. Cross-consistency: C22 counts 7 road + 18 virtual = 25 = C21 long rides
   w/ decoupling ✓; C3/C4/C2 weekly numbers tie to K2 rows ✓.

**Verified results snapshot (default-relevant):** latest ride 2026-10-15,
FTP 250 W, 154 rides; mix virtual 112.6 h / road 34.1 h / mtb 15.0 h /
gravel 0.3 h; 90d: 5665 m climbing, 498.6 km, IF 0.76 over 10 power rides;
long-ride decoupling: road mean 6.4 % (n=7), virtual 0.83 % (n=18).

**Next:** write `apps/cycling.html` (Great Wave, structure markup, 22
queries, controls + cross-filter + focus banner), then `anfra validate`
(data_app), test gates, pre-commit.


## 2026-10-26 (evening) — app authored, all gates green

**17:3x — `apps/cycling.html` written** (~1490 lines, single self-contained
file): Great Wave palette (parity with running.html incl. dark mode),
Basecoat controls, 17 ECharts + 4 KPI tiles, 22 queries. Ride-type semantic
colors (`--chart-road/virtual/mtb/gravel`) + %FTP zone ramp (`--chart-z1..z6`).
Controls per design: `dates` → every date-driven query on grain-native field
(NOT the KPI tiles / appMeta / weightHistory / fitnessTrend); `weekCap`
(week_start before to+1d) → fitnessTrend only (full history capped at range
end); `rideType` + `rideMix` cross-filter → the 12 activity-grain type-split
views (donut itself stays the navigator). K2 math in JS (currentMonday +
4-prior-Mondays slicing). Default window = data-relative last 90d, applied
once on appMeta's first success unless the user touched the range first.
C16 drift alarm = shape (diamond) + color, never color alone. W/kg carry-
forward via weightLookup (§8.5); connectNulls:false.

**17:4x — static gate:** `anfra validate` → `diagnostics: []`, no data_app
warnings (SRI pins + no local refs). Extracted all 22 AQL blocks
(anfra_utils.extract_aql) and ran each through `anfra query` sequentially:
21/22 OK; **weightHistory failed** — I'd referenced `weekly_summary.
avg_weight_kg` (raw dimension) as a measure; the model measure is `avg_weight`
(= avg(avg_weight_kg)). One-line fix in the app; re-ran → 22/22 OK. **Static
gate met: validate clean + every embedded query executes.**

**17:5x — tests added:**
- `tests/anfra/test_anfra_queries_cycling.py`: all cycling AQL blocks execute
  (server down) + expected count 22. Fixture `cycling_blocks` moved to
  `tests/anfra/conftest.py` (shared with the chart test).
- `tests/integration/test_build_db.py`: `test_ride_type_derivation`
  (virtual 106 / road 34 / mtb 13 / gravel 1 / EBike NULL 1; 0 non-rides
  typed) + `test_icu_ftp_density` (154/155 rides, 220–250 W, 4 distinct;
  the null is the EBike ride — SQL-verified before pinning).
- `tests/anfra/test_chart_render_cycling.py`: headless SSR render of every
  cycling chart with real query results (node + echarts 6.1.0 SVG). Extends
  the running harness pattern with a nullable YAML parser — longDecoupling
  rows legitimately contain nulls, and the original parser would turn them
  into the string "null" (NaN in JS), masking or faking failures.

**Results:** `pytest -m anfra --no-cov` → 6 passed, 63 skipped (skips = the
MCP-live equivalence tests, correctly skipping while the server is down);
`pytest tests/anfra -m charts` → 2 passed (running + cycling harnesses, zero
setOption throws across all 17 charts); `pytest tests/integration/
test_build_db.py` → 9 passed (7 existing + 2 new). Harness first-row logs
confirm sane data end-to-end (nulls preserved, month grain `2024-10-01`,
`is_long=1` flags, weight history from 2012).

**Port note (user):** a sibling worktree may seize 7878 — check before
serving, pick another port if taken.

**Next:** full suite + pre-commit + commits; serve on a free port; handover
(user verifies UI per §9 acceptance — I cannot drive a browser).

## 2026-10-26 (wrap-up) — served + live-verified + handed over

**18:0x — full suite:** 152 passed / 65 skipped (server-down run), coverage
85.25 % (floor 70). Commits: `f8bdfd8` (feat: cycling data app) and
`8b19e66` (test: gates) — pre-commit passed both times (ruff reformatted
the test files once; re-staged).

**18:1x — serve + MCP-live layer:** port 7878 was still free; `anfra serve`
now holds it (instance 40e7d68a90cdc0f4, v0.13.3, sidecars ok). App served
at http://127.0.0.1:7878/apps/cycling (200). Re-ran the MCP-live layer
against the running server (it had auto-skipped while the server was down):
**65/65 passed** — the cycling_* / ride_type / ftp_ref extension breaks no
existing contract.

**Handover:** static gates all green (validate clean, 22/22 queries, 17/17
charts SSR-render, full pytest). Browser-level acceptance (§9) needs human
eyes — asked the user to verify per the checklist.
