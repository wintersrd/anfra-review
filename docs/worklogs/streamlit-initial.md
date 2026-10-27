# WORKLOG — Cycling Data App (Streamlit build)

Spec: `docs/cycling-app-spec.md` (tech-agnostic, v1.0). Build path: **Streamlit**
(Appendix B). Quality gate: headless app-execution test (AppTest) running the full
script with zero exceptions + expected component count.

All times CET. Worktree branch: `feat/cycling-app`.

---

## 2026-10-26 16:37 — Orientation

- Read `AGENTS.md` (repo + global), the full spec, sync script, AML models,
  dataset, `streamlit_app/*`, tests, theme, pre-commit config.
- Build path decision: repo name (`cycling-streamlit`) + user-stated gate
  ("headless app-execution test ... zero exceptions") + Appendix B Streamlit
  session notes → Streamlit build, NOT the anfra-native path (so the
  `build-data-app` skill does not apply).
- Data access decision: per user instruction ("reader-snapshot and
  import-bootstrap rules"), the app reads `data/running_reader.duckdb`
  **read-only** directly (pattern of `streamlit_app/queries.py`), not via the
  anfra MCP. Keeps the app runnable headless without `anfra serve`.

## 2026-10-26 16:43 — Environment bootstrap

- `data/running*.duckdb` are gitignored → copied `.env` (never printed) and
  `.anfra/data_sources.yml` from `~/repositories/running-analytics` per user.
  DB will be rebuilt from committed `data/raw` via `--build-only` (deterministic).
- Tooling present: duckdb CLI v2.0.0, uv 0.9.26, node v26.10.0. `uv sync` started.

## 2026-10-26 16:44 — Data reconnaissance (committed data/raw)

- Rides (sport_group='ride'): **155** = VirtualRide 106, Ride 34,
  MountainBikeRide 13, GravelRide 1, **EBikeRide 1**.
- Ride era: first rides Oct 2024; per-ride detail (power/cadence/temp) dense
  only from ~Oct 2025 — matches spec §3.3.
- Field availability (rides): weighted_avg_watts 86, avg_cadence>0 86
  (36 rides at exactly 0.0 rpm = coast/idle artifacts → the §8.4 `>40 rpm`
  guard is essential), decoupling 84, avg_temp_c 47, icu_joules 86.
- Long rides (≥4500 s): 36, of which 25 have decoupling (range −3.8…+16.1%).
- weekly_by_category: category **`Ride`** = the cycling category (772 wks,
  1778 h — full 2012→ history; per-activity ride detail only exists Oct 2024+,
  exactly the §3.3 "weekly aggregates reliable, per-activity sparse" split).
- weekly_summary: 772 weeks 2012-01-09→2026-10-19; avg_weight_kg present 293,
  dense in the recent era (all recent weeks have weight → W/kg §8.5 viable).
- Cadence distribution (qualifying, >40 rpm): p10 85.5 / median 93 / p90 97.6.

## 2026-10-26 16:45 — Spec-owner decisions (asked, answered)

1. **FTP constant = 240 W** (§8.1 case 2; no per-activity FTP in data).
   Committed default in the data layer; env override `CYCLING_FTP_WATTS`
   (set to `0`/empty → case-3 "FTP not configured" path, exercised in tests).
2. **EBikeRide → excluded** (ride_type stays NULL → not a Ride per §4;
   keeps motor-assisted power out of %FTP/IF analytics).

## 2026-10-26 16:45 — Interpretation decisions (documented, spec-literal)

- `hr_decoupling` (spec §3.1) ↔ existing `activities.decoupling` column
  (percent, positive = drift — semantics identical, name differs; flagged to
  spec owner in final report rather than silently guessed).
- `work_kj` = `icu_joules/1000.0` — formula given verbatim in spec §3.1.
- `ride_type` derived from `type` exactly like the running model's
  `run_surface` precedent: Ride→road, VirtualRide→virtual,
  MountainBikeRide→mtb, GravelRide→gravel; EBikeRide and non-rides → NULL.
  Lands as a **derived column in the sync script** (DB + reader snapshot) and
  as AML dimensions (`ride_type`, `work_kj`, `hr_decoupling`) so the semantic
  layer stays the single source of truth for both build paths.
- Default window: spec §6.1 table says preset default "Last 30 days" but §6.2
  and acceptance criterion 1 say the app loads on a **90-day** window
  (latest-activity-relative). Going with 90-day default (§6.2 + AC1 win);
  preset list unchanged. Flagged in final report.
- Cadence buckets (C12): spec cites §8.6 there, which defines *hilliness* —
  the bucket edges are a spec gap. Chosen (left-inclusive, en-dash labels to
  match PACE_BUCKETS style): `<75`, `75–85`, `85–95`, `95+` rpm — informed by
  the tight 85–100 rpm qualifying distribution. Flagged in final report.
- K2/C3/C4 date bounds: sidebar bounds derived from **ride** dates (cycling
  app; §6.2 "latest activity date" read as latest ride). K2 "current week" is
  literal wall-clock today per §4; K3/K4 windows are wall-clock 90 d per §7.
- Timezone: `start_local` is the athlete-local timestamp; all week/month
  bucketing via `date_trunc` on it (§4 satisfied; same approach as running app).

## 2026-10-26 17:05 — ARCHITECTURE PIVOT (user direction)

> "core data layer should be built using the anfra backend and data model and
> queried via the anfra_client helper library, same as the running app. direct
> sql queries are to be used for data validation only"

- The app's live data layer becomes **AQL via anfra_client** (mirrors
  `app.py` ↔ `queries_aql.py`), NOT direct DuckDB.
- `cycling_queries.py` (already written + verified) is re-designated the
  **SQL validation oracle** (mirrors `queries.py` — kept, not deleted; used by
  the new AQL↔SQL equivalence tests only).
- New `streamlit_app/cycling_queries_aql.py`: same function surface, every
  query expressed as AQL against the semantic layer, executed by `anfra serve`
  (server owns the DuckDB lock; no reader snapshot in the app path).
- Metric math moves into `datasets/running_analytics.dataset.aml` as cycling
  metrics (grain-scoped by `where(activities.ride_type is not null)`, i.e.
  EBike excluded by definition): cycle_distance_km, cycle_time_h,
  cycle_elev_gain_m, cycle_activities, cycle_speed_kmh, cycle_cadence_rpm,
  cycle_np_w, cycle_elev_per_km, cycle_decoupling_avg, cycling_load (weekly
  category='Ride'). Named `cycle_*` to avoid colliding with the existing
  sport-group-scoped `ride_distance_km` metric (which includes EBike).
- App composition kept client-side only where AQL cannot express it:
  weight carry-back (two queries + pandas ffill/merge — provably equal to the
  oracle because weight is week-constant, so Σ(np/w·t)/Σt = (Σnp·t/Σt)/w),
  temp-bucket −5 °C floor clamp (Σ km & Σ h per bucket, then recompute),
  K2 zero-ride-week padding (4-Monday reindex, wall-clock), %FTP zone case
  (custom dimension with thresholds computed from the FTP constant at
  runtime), IF = np/ftp.
- Gate consequence: the AppTest + equivalence tests are **MCP-live tests**
  (skip with reason when `anfra serve` is down), exactly like
  `test_app_apptest.py` / `test_queries_aql_equiv.py` for the running app.
  `anfra serve` must run FROM THE WORKTREE (own DB + lock).

## 2026-10-26 16:52 — Data layer v1 (now the SQL oracle)

- `streamlit_app/cycling_queries.py`: 23 functions, all smoke-tested green on
  the 90-day window + empty window + single-type filter. Fixes hit: DuckDB
  rejects `:name` params (use `?`/list); pandas Timestamps normalized to
  `dt.date` in `date_bounds()`. Reader-snapshot direct access retained for
  tests via `CYCLING_DB` env override + conftest monkeypatch pattern.

## 2026-10-26 16:47 — Plan (original; step 4 now = SQL oracle per 17:05 pivot)

1. Branch `feat/cycling-app` in opencode worktree (done).
2. Model extension: sync-script `ride_type` derived column + AML dims;
   `--build-only` rebuild; extend fingerprint tests (ride_type derivation).
3. Theme: add ride-type colors (road=blue, virtual=slate, mtb=ochre,
   gravel=green) to LIGHT/DARK + `RIDE_TYPE_ORDER`/`RIDE_LABELS`/helper.
4. Data layer `streamlit_app/cycling_queries.py`: reader-snapshot, read-only,
   import bootstrap, all K1–K4 + C1–C17 query functions, FTP constant.
5. App `streamlit_app/cycling_app.py`: §5 layout, §6 behavior (presets,
   ride-type multiselect, donut cross-filter + banner/clear, empty states,
   formatting §6.3, theme toggle, footer, per-component load log §9.9).
6. Tests: unit (bucket edges, helpers, theme additions), integration
   (cycling_queries vs fixture DB incl. K2 boundary case), and the GATE:
   `tests/integration/test_cycling_app_apptest.py` — full-script AppTest,
   zero exceptions, expected component count, empty-window rerun.
7. Gates: ruff/mypy/pre-commit, full pytest layers, `anfra validate` (AML
   changed), AppTest gate. Conventional commits per step. WORKLOG updated
   as I go.

---

## 2026-10-26 16:48–16:55 — Model extension landed

- `scripts/sync_intervals_icu.py`: `ride_type` derived column (Ride→road,
  VirtualRide→virtual, MountainBikeRide→mtb, GravelRide→gravel; EBikeRide and
  non-rides NULL). DB rebuilt via `--build-only`; verified counts.
- `models/activities.model.aml`: `ride_type`, `work_kj` (= icu_joules/1000,
  hidden), `hr_decoupling` (= decoupling, hidden) dimensions.
- `datasets/running_analytics.dataset.aml`: `cycle_*` metric group (each
  `| where(ride_type is not null)`) + `cycling_load` from weekly_by_category
  Ride. Named `cycle_*` to avoid clobbering the sport-group `ride_distance_km`
  (which includes EBike). `anfra validate` → valid.
- `theme.py`: ride color maps + `RIDE_TYPE_ORDER`/`RIDE_LABELS`/
  `ride_type_color()`.
- `cycling_queries.py` (SQL oracle) written & fully smoke-tested; DuckDB
  gotcha: `:name` params rejected → use `?` positional + list.

## 2026-10-26 17:05 — Architecture pivot (user instruction)

> "core data layer should be built using the anfra backend and data model and
> queried via the anfra_client helper library, same as the running app.
> direct sql queries are to be used for data validation only"

→ `cycling_queries_aql.py` is the app's live data layer (mirrors the
running app's queries/queries_aql split). The SQL oracle stays as the
equivalence-test validation twin (golden rule 5 pattern).

## 2026-10-26 17:00–17:08 — anfra server port hygiene

- Main-repo server (stale DB, no ride_type) held 7878 → my first serve got
  auto-assign port 51780; initial AQL smoke hit the WRONG server ("ride_type
  not found"). Killed both; user warned another worktree may seize 7878.
- **Decision: my worktree server runs pinned to `--addr 127.0.0.1:7879`**;
  all dev/test runs export `ANFRA_MCP_URL=http://127.0.0.1:7879/mcp`
  (client + tests are env-aware). Eliminates cross-worktree DB confusion.
  NOTE: user's main-repo `anfra serve` was stopped in the process — restart
  it when needed.

## 2026-10-26 17:08 — AQL gotchas found via raw /api/core.query diagnostics

1. `activities.decoupling` is NOT a model dim (only my `hr_decoupling`) →
   string conditions must filter `activities.hr_decoupling`.
2. String conditions comparing a date to a quoted literal
   (`week_start <= '2026-10-15'`) fail server typecheck → use the AQL date
   literal `week_start <= @2026-10-15` (no quotes).
3. Bare AQL compiles fine while `input.conditions` merging fails — reproduce
   via `POST /api/core.query` with `{"expr": ...}` objects (strings are
   rejected as invalid_request; the client wraps them in Condition objects).

All 23 functions now equivalent SQL↔AQL on the 90-day window (+ empty-window
and virtual-only spot checks): smoke FAILURES: 0. Dtype lessons for the equiv
suite: fetchdf → datetime64/arrow; MCP frames → ISO 'str' dates; compare at
day grain, cast numerics to float64.

## 2026-10-26 17:10 — App + resilience smoke

- `cycling_app.py` written (17 components + 4 KPIs, cross-filter donut,
  FTP-gated power section, load log §9.9, footer data currency).
- Full-script AppTest: **zero exceptions**, 4 metrics, 23 loads logged,
  none failed (~1.5 s total query time).
- `data_currency` custom-metric trick failed (date dims are not pipable) →
  rewritten as date-desc first-row page + plain count (2 tiny queries).
- FTP case-3 (`CYCLING_FTP_WATTS=0`): app runs clean, FTP metric "—", power
  section shows the §8.1 empty state.
- Empty window (2013): app runs clean; 19 loads (power short-circuits), all
  friendly empty states. K3 correctly still reports wall-clock 90d values.

## 2026-10-26 17:13–17:16 — Test suite

- `tests/conftest.py`: `cycling_mod` fixture (oracle wired to fixture DB).
- `tests/unit/test_cycling_units.py`: theme ride colors, constants (en-dash
  buckets, EBike exclusion, 4500 s), `_ride_clause`, `current_ftp` contract
  (both layers), zone/cadence case expressions.
- `tests/integration/test_cycling_queries.py`: oracle vs fixture — ride
  universe = 154 (155 rides − 1 EBike), K2 zero-ride-week contract, wall-clock
  K3, guards (watts>0, cadence>40, ≥1 km, temp floor −5), long-ride
  threshold, empty windows, filter narrowing.
  - Fixes during bring-up (my test assumptions, not code bugs): EBike math
    154 not 155; fixture has a week whose rides ALL lack distance_m
    (SUM → NaN — allowed); `str(Timestamp)` carries `00:00:00` (day-grain
    compare).
- `tests/integration/test_cycling_aql_equiv.py`: 17 table-driven + 7 scalar
  AQL↔SQL equivalence cases, day-grain key normalization, env-aware server
  skip.
- **GATE** `tests/integration/test_cycling_app_apptest.py`: full-script run —
  zero exceptions, 4 KPI labels, sidebar contract (90d default preset),
  load-log ≥20 entries & no failures, empty-window rerun, FTP case-3.
  - Gate's `_server_up` now uses `AnfraClient.from_env()` (env-aware, honors
    ANFRA_MCP_URL) — the running app's gate uses the env-blind constructor.
- `test_build_db.py`: `ride_type` derivation pinned (106/34/13/1/NULL, EBike
  NULL, non-rides NULL).
- Layers: unit+integration offline 43 green; live equiv 25 green; gate 3/3.

## 2026-10-26 17:17–17:25 — Gates, matrix, commits

- **Lint/type**: `ruff check` + `ruff format` clean (fixes: zip strict=,
  wrapped signatures). `mypy` FAILS with `Duplicate module named conftest`
  (tests/anfra_client/conftest.py vs tests/anfra/conftest.py) — verified
  PRE-EXISTING at base 989eb9a (git stash → repro), not introduced here;
  left untouched, noted for the report.
- **pre-commit** `run --all-files`: PASSED (ruff + format + unit layer).
- **Full suite** (server up on 7879 via ANFRA_MCP_URL): **276 passed,
  23.27 s, coverage 88.08 %** (floor 70). cycling_app 86 %, both data
  layers 96 %.
- **anfra validate**: valid. **Down-half** (server nominally down;
  ANFRA_LIVE_TESTS=0): tests/anfra (validate/queries/chart SSR) 4 passed —
  test matrix complete: unit ✓ fixture-integration ✓ MCP-live (both apps)
  ✓ CLI/charts ✓.
- **Equivalence bring-up fix**: one order-dependent failure — two rides
  share (day, name); fixed by sorting both sides by key+numeric columns
  before compare (deterministic pairing), not by weakening the assertion.
- **Port incident**: a foreign worktree's server seized default 7878
  (user predicted this). My serve is pinned `--addr 127.0.0.1:7879`; all
  clients/tests go through `ANFRA_MCP_URL=http://127.0.0.1:7879/mcp`.
  The env-blind `http://127.0.0.1:7878/mcp` default bit once — gate's
  `_server_up` made env-aware as a result.
- **Commit lesson**: pre-commit stashes unstaged tracked files but leaves
  untracked ones — first commit attempt failed because the untracked unit
  test imported ride colors from an unstaged `theme.py`. Fix: stage
  `theme.py` with commit 1. Series landed (each pre-commit green):
  1. `1c39df6` feat: cycling semantic layer (ride_type + cycle_* + theme)
  2. `e390f64` feat: cycling SQL oracle + fixture tests
  3. `0c0aefd` feat: cycling AQL data layer + equivalence suite
  4. `9ef1dbb` feat: cycling Streamlit app + AppTest gate + unit tests
  5. docs: WORKLOG + AGENTS.md (this commit)

## Outcome

Delivered per spec: 4 KPIs + C1–C17, SQL↔AQL equivalence pinned by tests,
full-app headless gate green (zero exceptions), semantic layer extended
(ride_type, work_kj, hr_decoupling, cycle_* metrics). Open items for the
spec owner: FTP 240 W constant; EBikeRide excluded; cadence bucket edges
(spec gap); §6.1 "Last 30 default" vs §6.2/AC1 90-day (chose 90);
hr_decoupling ↔ activities.decoupling mapping; work_kj = icu_joules/1000.

## 2026-10-26 17:30–17:40 — Completion review (/complete-work)

Three review agents (architecture, structural/QA, UI/UX) over the branch
diff. Verdicts: APPROVED / APPROVED-with-MEDIUM / no-CRITICAL-2-HIGH.

**Fixed immediately (HIGH + cheap spec-fidelity items):**
- H1 cross-filter clear was a no-op until the next rerun: `st.rerun()` now
  fires on ANY picked≠focus change (incl. deselect). Fixed in BOTH apps
  (bug inherited from app.py).
- H2 / AC2: C12 caption now shows the qualifying ride count (query was
  already there, unwired).
- C16 spec fidelity: window-mean line + red tint for >+8% drift points.
- C2 ramp guardrail anchored to y2 (was floating on the load axis);
  fixed in both apps (inherited).
- §6.4: empty-state messages now name the active ride-type filter.
- §6.3: K3 delta km now 1dp; dead `setdefault` line removed.
- Gate test added: pre-seeded cross-filter focus run (banner, healthy
  load log, C12 count wiring).

**Tech-debt register (MEDIUM/LOW — this repo has no Gitea; recorded here):**
- M1 cross-filter state visible only at the donut banner; add a global
  status line/sidebar hint (both apps).
- M5 night mode does not theme stAlert/widget chrome; add stAlert CSS +
  dark base config (shared with app.py).
- M6 preset radio lacks a "Custom" state; same-preset re-click is a no-op
  (both apps; inherited design).
- L1 section labels ("Terrain & weather", "Endurance") vs spec §5 wording
  — spec-owner FYI, kept deliberately.
- L2 y-axis "hours" titles on C6/C7/C12 stacked charts.
- L3 hover templates on C3/C6/C7/C9/C12 (W/kg 2dp, per-type share).
- L5 C4 heatmap month labels on All-time (raw week dates overlap).
- L6 presets compute off max_date (data-relative) not wall clock (§6.2).
- Test-coverage gaps (QA review): AC5 caption text, AC6 number-format
  spot-checks, AC7 night-toggle assertions in AppTest.
- Accepted-by-design (arch review): FTP env changes live ≤300 s in cache;
  oracle/AQL constant duplication is the deliberate test contract.

## 2026-10-26 18:2x — Comparative reviews of the two build paths

User asked for adversarial + complimentary reviews of this Streamlit build
vs the parallel anfra-native build (~/repositories/cycling-anfra, same
spec/base commit) from two personas (data-platform owner, non-technical
builder), plus a deployment recommendation. Notes in `reviews/` (6 files).

Most consequential finding (recorded against this build): the anfra build
discovered per-activity `icu_ftp` in the raw NDJSON (240→250 W) and
implemented spec §8.1 case 1; our build uses the owner-approved 240 W
constant — chosen without the raw-layer knowledge that case 1 was
implementable. K4/C7/C8/C9 are therefore ~4 % mis-zoned vs per-activity
FTP. Recommended follow-up if this app is canonized: land `ftp_ref` in the
warehouse (their extension), switch current_ftp() to it, re-run gates.





## 2026-10-26 ~18:00 — Skill-vs-technology hypothesis (reviews/6)

Spec owner challenged the recommendation's premise: biggest issues came from
skill quality, not technology; what would a Streamlit skill modeled on the
anfra one change? Wrote `reviews/6-streamlit-skill-hypothesis.md`:

- Premise check: ~70% right. All *correctness/UX* deltas (FTP recon gap,
  design agreement, a11y floor, manual-vs-committed checks) were skill-borne
  and portable. The irreducible technology core is *enforcement/posture*
  (sandbox, definitions-by-physics, one artifact, host integration) vs
  *capability/assurance* (AppTest, pytest, typing, ceiling).
- Key subtlety: the anfra skill is good partly BECAUSE the platform is
  constrained — porting it ports the checklist, not the physics that made the
  checklist cheap to follow.
- Revised recommendation: Streamlit tier becomes defensible as DEFAULT iff the
  skill exists AND CI re-creates enforcement (banned-import policy tests,
  mandated equivalence + AppTest suites, coverage floors, single AML
  gatekeeper owning both skills — the cycle_* vs cycling_* fork is the drift
  cautionary tale). Otherwise physics beats policy for a platform default.
- Cheapest move either way: cross-pollinate the skills (raw-payload
  interrogation → anfra skill; committed-equivalence + headless gate mandate →
  whichever ships next) before funding a second skill.

## 2026-10-26 ~18:20 — anfra-streamlit-apps skill built + validated + installed

Actualizes reviews/6: the hypothetical Streamlit skill, for a clean-session A/B.

Built `skills/anfra-streamlit-apps/` (source of truth in-repo):
- `SKILL.md` — 7-step workflow mirroring build-data-app's structure, with the
  architecture-as-law diagram (AML ← oracle/live ← app-render-only), mandated
  worklog format (step 0), raw-payload interrogation (icu_ftp tale), design
  agreement + declaration list, data-layer-before-UI, gates, handover.
- `references/client.md` — anfra_client surface + server/lock/port rules +
  the 7 AQL gotchas that bit this build (date literals, hidden dim names,
  measures-vs-dims, Timestamps, :name params, …).
- `references/design.md` — theme token contract, layout rhythm, four states,
  cross-filter pattern (incl. unconditional-rerun and AppTest limitations),
  formatting + a11y floor.
- `references/testing.md` — fixture conftest, unit pinning, equivalence
  (norm: numeric→float64, else day-grain string; sort keys+numerics), AppTest
  scenario checklist, server up/down matrix, commit order + pre-commit stash
  gotcha.
- `references/example/` — complete miniature (live layer, oracle, app,
  conftest addition, equivalence + AppTest suites) over run_distance_km etc.

Validation (the skeleton's promise): staged into streamlit_app/ +
tests/integration/, run against serve on :7879 — **8/8 green** (3-window
equivalence ×4 incl. narrowed filter; AppTest default/empty/filter/focus).
Issues found & fixed by validation: DuckDB/`.frame()` Arrow string dtypes
broke `dtype == object` norm (→ is_numeric_dtype/astype float64), AppTest
resolves relative paths against the caller file (→ Path(__file__).parents[2]),
missing `data.SURFACES` import, import order (ruff --fix) → re-validated 8/8.
Validation copies removed; `testpaths=["tests"]` keeps templates uncollected.

Installed (cp -r) to ~/.claude/skills/anfra-streamlit-apps and
~/.config/opencode/skills/anfra-streamlit-apps (both harnesses; identical).
