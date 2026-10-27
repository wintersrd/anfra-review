# WORKLOG — Cycling Data App (Streamlit build)

Spec: `docs/cycling-app-spec.md` (v1.0). Skill: anfra-streamlit-apps.
Branch: `cycling-streamlit` (work-in-place, no extra worktree, per owner).

## 2026-10-26 17:50 — Orientation & environment

- Read AGENTS.md, spec, skill + references (client/design/testing), existing
  `streamlit_app/` (app.py, queries_aql.py, queries.py, theme.py), sync script,
  AML models/dataset, tests layout, pyproject, pre-commit.
- `uv sync` OK. `duckdb` CLI present (`/opt/homebrew/bin/duckdb`).
  `~/.anfra/bin/anfra` present. Ports 7878/7879 free at start.
- Repo has `data/raw/` (synced today 16:37) but **no built DuckDB**; sibling
  `~/repositories/running-analytics` has `running.duckdb` + reader snapshot
  (built Oct 25) but **without** the cycling extension columns.
- Decision (D1): build the DB **in this repo** via the repo's own
  `scripts/sync_intervals_icu.py --build-only` from this repo's committed raw
  (fresher than the sibling's, same source). The sibling DB lacks the
  extension columns; modifying the sibling repo is out of bounds. No network,
  no API — honors "data comes from the existing DuckDB store" intent.

## 2026-10-26 17:55 — Raw payload interrogation (skill step 1, mandatory)

Grepped `data/raw/activities.ndjson` (1089 stubs + 499 real activities):

- **`icu_ftp` EXISTS in raw NDJSON** (per-activity FTP; 154 rides carry it;
  **all 86 rides with power carry it**; values 220/230/240/250). The warehouse
  never imported it — exactly the skill's recorded trap. → land it in the sync
  script + AML. FTP resolution §8.1 case 1 (per-activity) is fully satisfiable.
- Ride type distribution: VirtualRide 106, Ride 34, MountainBikeRide 13,
  GravelRide 1, EBikeRide 1 → 155 rides.
- Long rides (≥4500 s) with `decoupling` present: 25 → C16/C17 viable via the
  activities `decoupling` column (NOT `decoupling_calc`, which is run-stream
  computed; §3.1 `hr_decoupling` = the raw `decoupling` column).
- Cadence >40 rpm: 86 rides; temperature recorded: 47; power: 86 (earliest
  2024-10-05 — matches spec §3.3 "dense from Oct 2024").
- `weekly_by_category.category` values include `'Ride'` (capital R) → C2
  cycling_load = training_load where category='Ride'. 772 weeks (2012→2026).
- Latest ride 2026-10-15; weight present in 293 weeks.

### Field inventory (per skill; number → source)

| App quantity | Source |
| --- | --- |
| activity_id, start_local, name, distance_m, moving_time_s, elev_gain_m, avg_speed_ms, avg_cadence, weighted_avg_watts, avg_temp_c, trainer | `activities` table + AML dims [today] |
| `hr_decoupling` | raw column `decoupling` [today]; AML: new hidden dim `hr_decoupling` |
| `work_kj` | `icu_joules`/1000 [today]; AML: new dim `work_kj` |
| `ride_type` [extension] | new build-time column derived from `type` (Ride→road, VirtualRide→virtual, MountainBikeRide→mtb, GravelRide→gravel, EBikeRide→road) |
| `ftp_ref` [extension] | new build-time column `COALESCE(icu_ftp, <constant>)`; constant = env `CYCLING_FTP_WATTS`, default 250 W (latest observed icu_ftp) |
| `ctl/atl/tsb`, `avg_weight_kg` | weekly_summary [today] |
| `cycling_load` | weekly_by_category load where category='Ride' [today] |
| W/kg weight reference §8.5 | new build-time column `weight_ref_kg` (ride's ISO week avg weight, else most recent prior week's, else null) |

## 2026-10-26 18:00 — Interpretation decisions (numbered, per skill step 0/2)

The spec is the owner-approved declaration list (§5–§7 give grain/filters/chart/
empty-state per component; user instructed "build the app specified…").
Decisions taken by builder (B) unless noted:

1. **D2 (B)** — Default window = **Last 90 days, data-relative** (§6.2 + AC#1
   say 90-day default; §6.1's "(default)" mark on Last 30 days is inconsistent —
   §6.2/AC#1 win). Presets: Last 30 / Last 90 / YTD / All time, default 90.
2. **D3 (B)** — `EBikeRide` (1 activity) maps to `ride_type='road'` (outdoor
   ride; spec enum has no e-bike value; dropping it would silently lose a ride).
3. **D4 (B)** — K2/K4 honor the ride-type filter like K3 (all three are
   activity-grain KPIs; spec calls it out only for K3). K1 is type-free.
4. **D5 (B)** — FTP constant: `CYCLING_FTP_WATTS` env at build time, default
   250 W. With it, ftp_ref is never null in practice; §8.1 case-3 ("FTP not
   configured") is implemented + unit-tested but unreachable on default data.
   K1 = ftp_ref of the most recent ride ("current").
5. **D6 (B)** — Cadence buckets for C12: spec §7-C12 cites §8.6 which is
   *hilliness* — bucket edges are unspecified. Chosen (left-inclusive,
   en-dash labels): `<70`, `70–80`, `80–90`, `90–100`, `100+` rpm.
6. **D7 (B)** — C13 "rides with cadence and speed" uses the §8.4 guard
   (`avg_cadence > 40`) consistently with all other cadence components.
7. **D8 (B)** — C8 includes the optional second series (mean %FTP) — trivially
   expressible once ftp_ref is a column, so included per §7-C8.
8. **D9 (B)** — C1 spans earliest week → window end regardless of date_from
   (§7-C1 "from earliest available week to window end"); date_to honored.
9. **D10 (B)** — `date_bounds()` for the cycling app = min/max date over rides
   only (footer "Data through …" refers to rides).
10. **D11 (B)** — C9 mean weighted watts = duration-weighted (§8 preamble
    "sums are duration-based"); W/kg = per-ride watts/weight_ref_kg,
    duration-weighted per week, gap when no resolvable weight.
11. **D12 (B)** — K2 "current week" = ISO week of **wall-clock today** (§4),
    `today` parameter injectable for tests; 4 preceding complete weeks are
    Mon(M−28)…Mon(M−7). K3/K4 windows are wall-clock 90 days (§7 wording).

## 2026-10-26 18:05 — Plan (commit sequence per skill testing.md)

1. sync-script extension (icu_ftp, ride_type, ftp_ref, weight_ref_kg) +
   offline CSV regeneration + DB build + `.anfra/data_sources.yml` (local,
   git-ignored) → `feat:` commit.
2. AML extension (activities dims + dataset cycling metrics) + `anfra validate`
   → `feat:` commit.
3. Oracle `cycling_queries.py` + fixture tests → `feat:` commit.
4. Live layer `cycling_queries_aql.py` + equivalence tests (serve up, pinned
   port 7879) → `feat:` commit.
5. theme ride register + `cycling_app.py` + AppTest gate + unit tests →
   `feat:` commit.
6. Docs (README/AGENTS) + final gate table → `docs:` commit.

## 2026-10-26 18:15 — Step 1 done: sync extension + DB build

- `scripts/sync_intervals_icu.py`: icu_ftp column + import; derived columns
  ride_type / ftp_ref / weight_ref_kg in `build_db()` (ftp constant env
  `CYCLING_FTP_WATTS`, default 250); `--from-ndjson` offline CSV regeneration.
- Regenerated activities.csv (499 rows, stubs dropped 1089) and rebuilt
  `data/running.duckdb` + reader snapshot through the sync script (v0.10.0
  path). Fingerprints unchanged (499/187/772/1033/71) — integration layer
  green. ride_type: virtual 106 · road 35 · mtb 13 · gravel 1. ftp_ref: 154
  rides carry icu_ftp (220/230/240/250), 1 ride → constant 250. K1 current
  FTP = 250 W (latest ride's icu_ftp). weight_ref_kg resolvable for 155/155.
- `.anfra/data_sources.yml` (git-ignored) → this repo's running.duckdb.
- Issue: first `git commit` aborted — ruff-format hook reformatted the sync
  script; re-staged and committed (`a09d5e0`). Unit 42 + integration 44 green.

## 2026-10-26 18:25 — Step 2 done: AML extension

- `models/activities.model.aml`: dims ride_type, ftp_ref, weight_ref_kg,
  icu_ftp, hr_decoupling (over raw `decoupling`), work_kj (icu_joules/1000).
- `datasets/running_analytics.dataset.aml`: ride_distance_km switched to
  ride_type-based; new metrics ride_time_h, ride_elev_gain_m,
  ride_activities, ride_speed_kmh (§8.8), ride_weighted_cadence (§8.4),
  ride_avg_watts, ride_w_per_kg (§8.5), ride_intensity_factor (§8.3),
  ride_pct_ftp (§8.2), ride_elev_per_km (§8.6), cycling_load
  (weekly_by_category Ride); `cycling` view group.
- `anfra validate` → valid: true, no diagnostics.
- Issue: an edit dropped the ride_time_h body (caught by re-reading the file);
  restored. Added decision D13 below.
- **D13 (B)** — K2 4-week mean = sum of the 4 calendar weeks' km ÷ 4
  (no-ride weeks count as 0), computed from a week-grain fetch in both data
  layers; "this week" = partial current ISO week (0 km when no rides yet).

## 2026-10-26 19:00 — Step 3 done: SQL oracle + fixture tests (commits 4a/4b)

- `streamlit_app/cycling_queries.py`: 22 functions; constants RIDE_TYPES,
  FTP_ZONE_LABELS/EDGES (§8.2), CADENCE_BUCKETS/EDGES (D6), guards
  (power>0, cadence>40, ≥1000 m, temp floor −5 °C), LONG_RIDE_MIN_S.
  Env-overridable path `$CYCLING_DB` (AppTest fixture hook).
- Headless smoke (skill step 3): all fns × default/empty/narrowed — 0 errors.
  Bugs found & fixed: (a) `km or 0` doesn't catch pandas NaN (NaN is truthy)
  → K2 mean went NaN; now `pd.isna` guard. (b) `date_bounds` returned
  Timestamps whose `.isoformat()` carried `T00:00:00`, skewing window edges
  (explains a 13-vs-14-week discrepancy in the ramp query) → returns
  `dt.date` now.
- Data reality logged: virtual trainer rides carry NO distance/elev/speed
  (time+power only) → K3/volume/scatter legitimately empty for virtual-only;
  outdoor rides mostly report cadence 0.0 (guard catches); weekly Ride load
  has 3 zero-load weeks in the default window (data, kept); 25 long rides
  with decoupling overall (6 in default window; C17 groups road/virtual).
- `tests/integration/test_cycling_oracle.py`: 27 tests, pinned fingerprints
  (K2 avg 29.7026 km; K3 5665 m / 498.6 km wall-clock; K4 IF 0.7591/10 rides;
  mix road 20.99/virtual 7.15/mtb 6.86 h; load-ramp 14 weeks, first-week gap;
  power 10/34; C9 6 of 11 weeks with watts, W/kg null wherever watts null).
- Process slip: one `pytest | tail` pipeline hid a failing assert and the
  commit landed red (miscounted 7 vs 6 power weeks) — fixed in the same
  push (`test:` fixup). Gate re-run: unit 42, integration 71, oracle 27 green.
- Commits: `feat: cycling SQL oracle + fixture integration tests` + fixup.

## 2026-10-26 19:00 — Step 4: live AQL layer + equivalence suite

- `streamlit_app/cycling_queries_aql.py` (~500 lines): import bootstrap, same
  constants + 22 function names/shapes as the oracle. Mechanisms where AQL
  differs from SQL: ramp = `df["load"].diff()` (D14, first visible week gap);
  K2 week-grain fetch ÷ 4 (D13); C9 = two queries (watts POWER-filtered,
  W/kg POWER+weight-filtered) outer-merged on week_start; zone/cadence/temp
  buckets as custom-dimension `case(...)` arms.
- Issues hit:
  1. `greatest(a, b)` in a custom dimension → `AnfraCompileError: Cannot
     redeclare field` — the comma inside `greatest()` breaks the renderer
     (same family as the multi-element comma gotcha). Fix: `case(when:
     floor(t/5)*5 < -5, then: -5, else: floor(t/5)*5)`.
  2. `speed_by_temp` grouped 7 no-temp rides into a NaN bucket — added the
     oracle's `avg_temp_c is not null` guard to the live filters.
  3. Empty-window `rides_with_power`: live returned 0, oracle returned NULL
     (SUM over no rows). A count of zero rides is 0 — fixed the ORACLE with
     `COALESCE(SUM(...), 0)`; both layers now agree, oracle fingerprints
     unchanged.
  4. Equivalence test initially called the wall-clock 90d KPIs with window
     args — their signature is `(types, today)`. Split into
     `test_kpi90_functions_equivalent`.
- Row-set semantics: live omits rows whose measures are all NULL (gap-point
  weeks, e.g. C9 weeks without power) while the oracle keeps them — identical
  charts, different row sets; `_norm` drops all-measure-missing rows on both
  sides before compare (documented in the test docstring).
- Gates: ruff check/format clean, mypy clean, equivalence + oracle suites
  80 passed (equiv: 10 typed fns × default/empty/narrow + 8 plain ×
  default/empty + 2 KPI90 × all/narrow + K2 + K1 + constants-pinned).
- `test_constants_pinned_between_layers` pins the 10 shared constants
  (buckets, edges, thresholds, labels) between oracle and live layer.

## 2026-10-26 19:20 — Step 5: theme register, app, AppTest gate

- `theme.py`: added `ride` color register to LIGHT/DARK (road cerulean
  #3E7CB1/#7FB3D8, virtual slate #6E7F92/#93A9BF, mtb ochre #C9A66B/#D9BC85,
  gravel pine #4A6B57/#8FB39A — spec §6.3 mapping), `RIDE_ORDER`,
  `RIDE_LABELS`, `ride_color()` with muted fallback; `surface` register and
  everything else untouched. Unit tests added to tests/unit/test_theme.py
  (ride keys per mode, distinct hex, labels, helper fallback).
- `streamlit_app/cycling_app.py` (~740 lines): §5 layout — header, KPI strip
  K1–K4 (K1 "FTP not configured" case-3 path; K2 exact delta vs 4-wk mean;
  K3 thousands-sep meters + km sub; K4 2dp IF + power-ride count), sections
  Fitness & load (C1 athlete-level CTL/ATL/TSB with pos/neg split dot traces,
  C2 load bars + ramp line + zero line), Volume & consistency (C3 km+elev,
  C4 W-MON calendar heatmap Mon-top with month band labels, C5 donut
  cross-filter source hole=0.6 desc-from-12, C6 stacked weekly hours with
  hours+share hover), Power (C7 %FTP zone stack Z1→Z6 with caption counts,
  C8 IF + mean %FTP dot second axis, C9 full-width watts bars + W/kg line),
  Speed & cadence (C10/C11 per-type monthly lines in ride colors, C12 cadence
  bucket stack, C13 scatter speed vs cadence colored by type with name+date
  hover, C14 hilliness lines, C15 temp-bucket bars with ride counts + artifact
  caption), Endurance & terrain (C16 scatter with mean line + >+8% warm tint
  dots + dotted alarm reference, C17 per-type bars with long-ride hover
  counts), footer data-currency + collapsed load-log expander table.
- `_run_query(key, fn, *args)` logs (key, ms, rows) to
  `st.session_state.load_log`; rows=-1 + st.error on failure; app keeps
  rendering. Cross-filter: donut `on_select="rerun"` customdata →
  `focus_ride_type`, banner names what stays unfiltered (C1/C2/C6, C16/C17),
  Clear button; the sidebar multiselect mirrors it (keyboard path).
- mypy note: the app layer types `_run_query`/`line` loosely (Any) matching
  the existing app.py style — the data layers carry the strict typing.
- Issues hit: (a) `AnfraClient()` bare constructor ignores ANFRA_MCP_URL
  (defaults to 7878) → AppTest `_server_up` probe skipped everything on the
  pinned 7879 serve; switched to `AnfraClient.from_env()`. (b) ruff caught a
  `DECoupling_ALARM_PCT` mixed-case typo + an invalid `f"{x :,}"` format
  spec — both fixed. (c) pandas-stubs typed pivot columns as str →
  strftime errors; reworked the label loop through explicit
  `pd.Timestamp(w)`.
- Gates: AppTest 4/4 scenarios green (default: all 23 load-log keys, no
  rows==-1, no st.error, no exception, FTP 250 + IF 0.76 rendered; empty
  window via date_input 2011; virtual-only multiselect narrowing with
  friendly K3 "—"; cross-filter pre-seed road + Clear via button click).
  unit+integration: 198 passed, 1 skipped (running-app apptest probes port
  7878 — nothing serves there in this session; correct skip), coverage
  88.72% ≥ 70% floor. ruff/mypy clean.

## 2026-10-26 19:55 — Step 6: docs + final gates

- Docs: README "Cycling app" subsection (what it shows, two-file data-layer
  pattern, run command, load-log keys as change-request vocabulary);
  AGENTS.md layout row for `cycling_app.py`.
- Port note for the final gate run: the pre-existing live-test guards
  (`tests/anfra_client/test_live_anfra.py`, `test_capability_matrix.py`,
  `test_app_apptest.py`) probe the DEFAULT port 7878 via bare
  `AnfraClient()` — with serve pinned on 7879 they silently skipped (17
  false-green skips). Fix chosen: run `anfra serve` on the default 7878
  (free) rather than patching pre-existing test guards; my own tests use
  `AnfraClient.from_env()` so they work either way. The pinned-7879 run had
  also passed: 283 passed / 17 skipped, cov 88.72%.
- Pre-existing (NOT from this work): `uv run mypy .` fails with a duplicate
  module "conftest" error (tests/anfra/conftest.py vs
  tests/anfra_client/conftest.py) — verified identical on the clean tree at
  4edd36f via git stash. All four cycling Python files pass mypy cleanly.
  AGENTS.md's `tests/charts` path in the testing map is also stale (chart
  tests live in tests/anfra/test_chart_render.py).

### Final gate table

| Gate                                        | Result                                        |
| ------------------------------------------- | --------------------------------------------- |
| `uv run ruff check .`                       | All checks passed                             |
| `uv run ruff format --check .`              | 47 files already formatted                    |
| `mypy` (cycling_app, both data layers, theme) | Success: no issues in 4 files               |
| `mypy .`                                    | 1 pre-existing conftest duplicate error (not from this work) |
| Full pytest, `anfra serve` on 7878          | **300 passed, 0 skipped, coverage 88.72%**    |
| — of which cycling                          | equivalence 43, oracle 27, AppTest 4, theme 6 |
| CLI half re-check (serve down earlier)      | tests/anfra: 4 passed                         |
| `anfra validate` (after AML step)           | valid: true                                   |
| AppTest quality gate (spec §9)              | 4/4 scenarios, zero exceptions, 23 load-log keys, no rows==-1 |

- Serve left running on the default port: `~/.anfra/bin/anfra serve`
  (http://127.0.0.1:7878). App: `uv run streamlit run streamlit_app/cycling_app.py`.
