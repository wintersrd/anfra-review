# Cycling Data App — Development Specification

**Version:** 1.0 · **Status:** Ready to build · **Audience:** implementer (may be non-technical; every
decision needed to build is in this document)

This is a **technology-agnostic** specification. It defines what the app shows, computes, and how it
behaves — not which framework renders it. Two independent builds are planned from this document
(one on the anfra/native path, one on Streamlit); both must satisfy the same acceptance criteria.

**How to read this spec**

- Components are numbered `C1`…`C17`. Build them in the order listed.
- "Data contract" lists every field the app consumes. Fields marked **[today]** exist in the
  current model; **[extension]** fields are provided by the planned cycling model extension
  (the extension itself is out of scope for this document — see §2).
- Every metric has an exact formula in §8. Do not invent variants.
- Anything your framework cannot express must degrade to the documented empty-state (§6.4), never
  an error panel.

---

## 1. Purpose

A one-page cycling analytics dashboard for a self-coached endurance athlete, complementary to the
existing running dashboard. It answers: *how much am I riding, how hard (relative to FTP), how
consistently, at what cadence and speed, over what terrain, and is my endurance quality holding up
on long rides?*

Non-goals: maps/routes, power-curve stream analysis, workout editing, multi-athlete support,
deployment/auth. V1 is single-user, local, read-only.

## 2. Model context (out of scope, but assumed)

The app reads the **existing analytics data model, extended for cycling**. This spec does not
define that extension. Implementers may assume the extension provides, at minimum:

- a **ride-type dimension** on activities (values: `road`, `virtual`, `mtb`, `gravel`; virtual =
  indoor trainer/Zwift) — the cycling analogue of the running model's run surface;
- an **FTP reference** resolvable per activity (see §8.1 for how the app consumes it).

All other consumed fields exist today (§3). If a consumption-marked field turns out to be absent
or differently named at build time, raise it with the spec owner rather than substituting a guess.

## 3. Data contract

### 3.1 Activity grain (one row per activity)

| Field | Availability | Unit / type | Notes |
|---|---|---|---|
| `activity_id` | [today] | text | stable key |
| `start_local` | [today] | local datetime | drives all date filtering |
| `name` | [today] | text | hover text |
| `ride_type` | [extension] | enum | `road` \| `virtual` \| `mtb` \| `gravel` |
| `distance_m` | [today] | meters | volume |
| `moving_time_s` | [today] | seconds | time + denominators |
| `elev_gain_m` | [today] | meters | climbing |
| `avg_speed_ms` | [today] | m/s | speed trend |
| `avg_cadence` | [today] | rpm (one-foot) | cadence analytics |
| `weighted_avg_watts` | [today] | watts | power analytics; sparse before ~Oct 2024 |
| `work_kj` | [today] | kJ (`icu_joules`/1000) | top-rides ranking |
| `avg_temp_c` | [today] | °C | environment; sparse |
| `hr_decoupling` | [today] | percent | positive = cardiovascular drift; sparse |
| `trainer` | [today] | bool | virtual/indoor corroboration |
| `ftp_ref` | [extension] | watts | FTP applicable to this activity (§8.1) |

### 3.2 Weekly grain (one row per ISO week)

| Field | Availability | Notes |
|---|---|---|
| `week_start` | [today] | Monday-start, local timezone |
| `ctl`, `atl`, `tsb` | [today] | athlete-level (ALL sports pooled) — labeled as such on-chart |
| `cycling_load` | [today] | from weekly-by-category data, category = cycling |
| `avg_weight_kg` | [today] | used for W/kg (§8.5) |

### 3.3 Data reality the UI must respect

- Per-activity detail (power, cadence, temp) is dense only from **October 2024** onward. Earlier
  weeks have reliable weekly aggregates but sparse per-activity fields.
- Therefore: **every power- and cadence-based component analyzes only activities that have the
  required field**, and its caption states the qualifying count (e.g. "148 of 155 rides with
  power"). No synthetic "unknown" buckets in power/cadence components.
- Weekly CTL/ATL/TSB history extends back to 2012 — fitness charts may show the long horizon.

## 4. Scope definitions

- **Ride** = any activity whose ride-type dimension is populated (road, virtual, mtb, gravel).
- **Long ride** = moving time ≥ 75 minutes (4500 s). Same threshold as the running app's long run.
- **Current week** = the ISO week (Monday-start) containing today.
- **Complete week** = an ISO week entirely in the past (its Monday ≤ start of current week − 7 days).
- **Timezone** = the athlete's local timezone. All week/month bucketing uses it; never UTC.

## 5. Layout

Single page, sections in this order. All section headers and two-column groupings mirror the
running dashboard's visual rhythm: full-width title → KPI strip (4 tiles) → sections of two charts
side-by-side (one full-width where marked).

1. **Header** — app title, one-line caption, theme toggle (light/dark).
2. **KPI strip** — `K1`–`K4`.
3. **Fitness & load** — `C1`, `C2`.
4. **Volume & consistency** — `C3`, `C4` / `C5`, `C6`.
5. **Power** — `C7`, `C8` / `C9` (full width).
6. **Speed & cadence** — `C10`, `C11` / `C12`, `C13` / `C14`, `C15`.
7. **Endurance & terrain** — `C16`, `C17`.
8. **Footer** — data-currency caption ("Data through {latest activity date} · {n} rides analyzed").

## 6. Global behavior

### 6.1 Filters

| Filter | Type | Values | Applies to |
|---|---|---|---|
| Date range | presets + explicit range | `Last 30 days` (default), `Last 90 days`, `Year to date`, `All time`; or from/to dates | **all** components, each on its grain-native date field |
| Ride type | multi-select | `road`, `virtual`, `mtb`, `gravel` (empty = all) | activity-grain components only (see per-component "Filters" line) |

**Cross-filter:** clicking a slice of the ride-mix donut (`C5`) focuses every applicable
activity-grain component on that ride type until cleared. A visible focus banner with a Clear
button is required. Weekly-grain components (`C2`, `C6`) and athlete-level fitness (`C1`) are
**excluded** by design (different grain); state this in the on-page notes.

### 6.2 Default window

Last 90 days, implemented as: `from = (latest activity date − 89 days)`, `to = latest activity
date` — relative to the data, not the wall clock, so the app renders correctly on stale data.
The date preset still recalculates from the wall clock when the user re-picks it.

### 6.3 Formatting

| Quantity | Format |
|---|---|
| km | 1 decimal |
| hours | 1 decimal |
| elevation m | integer, thousands separator |
| watts / FTP | integer |
| W/kg, IF | 2 decimals |
| %FTP | integer + `%` |
| cadence | integer + `rpm` |
| speed | 1 decimal + `km/h` |
| decoupling | 1 decimal + `%` |

Sort orders: time series left→right ascending; categorical bars descending by value unless a
canonical order is given. Colors: ride-type semantic mapping (road = primary blue, virtual = slate,
mtb = ochre/tan, gravel = green) consistent across every component; negative TSB / drift-above-8%
= warm alarm color; never rely on color alone for bucket identity (labels on hover/legend).

### 6.4 Empty states & guards

- A component whose filtered input has zero rows renders a friendly inline empty-state
  ("No rides in this window for the selected types"), never a stack trace.
- Division-by-zero/null → null (gap in the line), never 0 and never ∞/NaN text.
- If FTP is unresolvable (§8.1 case 3), power components render the empty-state text
  "FTP not configured" instead of charts.
- Null temperature / null decoupling rows are excluded from their components (caption counts state
  qualifying rides).

## 7. Components

Filters listed per component are **in addition to** the global date filter.

### KPI strip

**K1 — Current FTP** · value = FTP per §8.1; sub-caption "used for %FTP & IF". If case-3 FTP →
"FTP not configured" tile.

**K2 — Ride km: this week vs 4-week average** · this week's total ride distance (current ISO
week) vs mean of the 4 preceding **complete** ISO weeks; delta sub-caption with arrow. This
definition is exact — do not substitute "last 7 days".

**K3 — 90-day elevation gain** · Σ `elev_gain_m` over rides in the last 90 days (wall-clock);
sub-caption total distance. Honors ride-type filter.

**K4 — Avg intensity (IF), last 90 days** · duration-weighted mean IF over rides with power
(§8.3); sub-caption "n rides with power".

### Fitness & load

**C1 — Fitness trend** · line chart, weekly grain, from earliest available week to window end.
Series: CTL and ATL (left axis, continuous lines); TSB as a diverging series on the secondary
axis rendered in two visual parts — positive values (fresh) and negative values (fatigue) visually
distinct (e.g. dashed vs colored), with a zero reference line. Caption: "CTL/ATL/TSB are
athlete-level (all sports)". Filters: **date only**.

**C2 — Weekly cycling load & ramp** · bar chart (weekly `cycling_load`) + ramp-rate line
(§8.7) on secondary axis, with a horizontal zero line on that axis. Filters: **date only**.
Ramp spikes beyond ±(typical weekly load) are data, not errors — do not clip.

### Volume & consistency

**C3 — Weekly ride distance** · bars of weekly ride km + secondary-axis line of weekly elevation
gain (m). Filters: date only.

**C4 — Riding calendar heatmap** · grid: x = ISO week, y = weekday (Mon top), cell color =
daily ride km (null/zero = blank). Month labels under the x axis. Filters: date only.

**C5 — Ride mix (cross-filter source)** · donut of hours by ride type (hole ≈ 60%), sorted
descending starting at 12 o'clock. This is the cross-filter source (§6.1).

**C6 — Weekly hours by ride type** · stacked bars, one bar per week, segments per ride type in
canonical color order; hover shows hours + share per type. Filters: date only.

### Power

**C7 — %FTP distribution by week** · stacked bars: weekly hours per %FTP zone bucket
(§8.2 buckets, canonical order Z1→Z6). Restricted to rides with power; caption shows qualifying
count. Filters: ride type.

**C8 — Intensity trend** · line chart, monthly grain: duration-weighted mean IF (§8.3). Optional
second series: mean %FTP on a hidden shared scale — only if trivially expressible; otherwise
IF alone. Filters: ride type.

**C9 — Power & weight (full width)** · weekly line chart: mean weighted watts (left axis) and
W/kg (§8.5, right axis), rides with power and known weight; weeks lacking weight show a gap in
the W/kg series only. Filters: ride type.

### Speed & cadence

**C10 — Monthly avg speed by ride type** · one line per ride type (≥1 km rides), gaps where a
type has no data that month (do not bridge). Filters: ride type.

**C11 — Cadence trend by ride type** · monthly duration-weighted mean cadence (§8.4) per ride
type, same gap rule. Filters: ride type.

**C12 — Cadence distribution by week** · stacked bars of weekly hours in cadence buckets
(§8.6), rides with cadence only; caption with qualifying count. Filters: ride type.

**C13 — Cadence vs speed** · scatter, one point per ride with cadence and speed (x = avg speed
km/h, y = avg cadence rpm, color = ride type, hover = name/date). Filters: ride type.

**C14 — Monthly hilliness by ride type** · monthly elev m per km (§8.6) per ride type, lines.
Filters: ride type.

**C15 — Speed vs temperature** · bars: mean avg speed (km/h) per 5 °C temperature bucket
(bins `[lo, lo+5)°C`, floor at −5; only rides with temperature), plus ride-count sub-bars or
hover counts. Caption notes warmer-is-faster is the expected artifact, not fitness. Filters:
ride type.

### Endurance & terrain

**C16 — Long-ride HR decoupling** · scatter per long ride (≥75 min, decoupling present):
x = date, y = decoupling %, hover = name; horizontal mean line. Values above +8% tinted alarm.
Filters: **date only** (already ride-type-derived data).

**C17 — Decoupling by ride type** · bars: mean decoupling per ride type over long rides, hover
shows qualifying ride counts. Filters: date only.

## 8. Metric definitions (authoritative)

All aggregations are over the filtered ride set; `t` = `moving_time_s`; sums are duration-based
(never unweighted means of per-ride values).

**8.1 FTP resolution.** Per activity: (1) if the model provides per-activity FTP, use it;
(2) else use the single configured current-FTP constant (build-time setting, displayed in K1);
(3) if neither exists → FTP case-3 (§6.4).

**8.2 %FTP & zones.** `%FTP = weighted_avg_watts / ftp_ref × 100`, per ride with power > 0.
Buckets, **left-inclusive** `[lo, hi)`: Z1 Recovery `<55` · Z2 Endurance `55–75` · Z3 Tempo
`75–90` · Z4 Threshold `90–105` · Z5 VO2max `105–120` · Z6 Anaerobic `≥120`. (Device-app zone
names may differ; the app's canonical buckets are these.)

**8.3 IF.** Per ride `IF = weighted_avg_watts / ftp_ref` (bounded to 2 decimals at display).
Aggregated IF = `Σ(IF·t)/Σt` over rides with power.

**8.4 Cadence.** Duration-weighted `Σ(cadence·t)/Σt` over rides with `avg_cadence > 40` rpm
(idle/coast artifacts removed — same guard as the running model's stride guard).

**8.5 W/kg.** Per ride: `weighted_avg_watts / weight_kg` where `weight_kg` = the ride's ISO
week's average weight; if that week has none, the most recent prior week's; if none ever → null.

**8.6 Hilliness.** `Σ elev_gain_m / Σ distance_m × 1000` (m per km), monthly, per ride type
(≥ 1 km rides only).

**8.7 Ramp rate.** `load(week) − load(week−1)` on weekly cycling load; the first week has no
value (gap).

**8.8 Speed.** `Σ distance_m / Σ moving_time_s × 3.6` (km/h) — a true distance-over-time mean,
never the mean of per-ride speeds.

**8.9 Decoupling.** As provided by the data (percent, positive = drift/fatigue). Never invert
the sign.

## 9. Acceptance criteria (both builds)

1. All 17 components + 4 KPI tiles render on the default 90-day window with the fixture dataset;
   none shows an error state.
2. Each power/cadence component's caption displays its qualifying ride count.
3. Selecting only `virtual` in ride type: C10–C15 show virtual-only data; C1/C2/C3/C4/C6/C16
   unchanged in shape (they are date-only or weekly); donut focus banner appears and clears.
4. Setting an impossible filter (window with no rides) yields friendly empty states everywhere —
   zero exceptions logged.
5. C1's caption marks CTL/ATL/TSB as athlete-level; C7–C9 captions reference FTP.
6. Formatting matches §6.3 exactly (spot-check: one km value, one IF value, one cadence value).
7. Theme toggle (if the build supports theming) re-themes charts as well as page chrome.
8. `K2` uses the §4 current-vs-4-complete-weeks definition — verify with a boundary date.
9. The app loads with no console errors and each component's first successful data load is
   observable (log or debug hook) for verification.
10. Static quality gates of the chosen build path all pass (anfra: semantic validation + every
    embedded query executes; Streamlit: the app-execution test suite runs the full script).

## Appendix A — Repo orientation (both builds run in the same repo)

- Model files: `models/*.model.aml`, dataset `datasets/running_analytics.dataset.aml`; the cycling
  extension lands here (see §2).
- Sample data: `scripts/sync_intervals_icu.py --build-only` builds the local analytics database
  from committed raw files (no network, no secrets); never build it with the plain DuckDB CLI —
  the storage format matters (see AGENTS.md).
- `AGENTS.md` at repo root holds the environment's hard-won rules; read it before building.
- Existing reference app: `apps/running.html` (anfra-native) and `streamlit_app/` (Streamlit) —
  style and behavioral parity with these is the bar.
- Quality gates live in `tests/`; each build adds its own gate per §9.10.

## Appendix B — Build-path notes (per session; not part of the tech-agnostic spec body)

**anfra session.** Use the build-data-app skill first. Known traps: multi-element AQL blocks need
commas between elements; `ctl/atl/tsb` are model *measures* while `fatigue/form/fitness/
training_load/ramp_rate` are raw dimensions in `weekly_summary`; qualify model measures explicitly
(e.g. `activities.total_time_s`); dataset metrics need no qualification. Gate: `anfra validate`
clean AND every embedded query executes against the live data source.

**Streamlit session.** The app imports helper modules from the repo root — keep the
location-independent import bootstrap at the top of the data layer. Editing imported modules
requires a process restart (app-script edits only need a browser rerun). Gate: the headless
app-execution test (runs the full script, asserts no exceptions and expected component count).
