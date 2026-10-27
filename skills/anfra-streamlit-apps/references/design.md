# Designing the Streamlit app

The look is Streamlit-native with repo theme tokens on top — never raw
default chrome, never bespoke CSS sprawl. A reader who has seen one app in
the family must feel at home in the next.

## Theme

One `streamlit_app/theme.py` owns the tokens: two dicts (`LIGHT`/`DARK`) with
the same keys — `page`, `card`, `ink`, `muted`, `border`, `grid`, `pos`,
`neg`, `surface`/type-specific color registers (`surface`, `ride`, …),
`heatmap` scale, `categorical` (8-step). Plus, per register: an `*_ORDER`
list, an `*_LABELS` dict, and a `*_color(theme, key)` helper with a `muted`
fallback. Night mode = `st.session_state["night"]` toggle; every chart
re-renders from the active dict (a toggle that only flips CSS but leaves
plotly in the wrong theme is a bug). `page_css()` injects the card/sidebar
chrome; `apply_layout(fig, theme, title, height=300)` applies the shared
plotly layout (transparent background, theme ink/grid).

If the repo has no `theme.py`, port one from the example rather than starting
blank — and unit-test the token contract (same keys in both dicts; registers
match their ORDER lists).

## Layout rhythm

- **KPI strip first**: `st.metric` tiles — value, a meaningful delta
  (vs previous period / 4-week mean), caption line for qualifying counts.
- **Sections** in spec order: a `section(title, caption)` header helper; the
  caption carries the definition ("duration-weighted mean IF over rides with
  power, §8.3-style guards") — definitions live on the page, not in a wiki.
- **Two-column grid** via a `queue()`/`flush_row(n)` pair of helpers:
  components enqueue, the row renders when full, `_render_cell` gives every
  cell the same empty-state treatment. Full-width (wide) components flush the
  row first.
- **Sidebar contract**, top to bottom: theme toggle → preset radio
  (Last 30 / Last 90 / YTD / All time) → date range → category/type
  multiselect (empty = all). Preset switch resets the date range
  (`prev_preset` in session state); manual date edits make the radio stale —
  acceptable, but the preset must win on next switch, never silently clobber.
- **Footer**: data currency ("latest activity 2026-10-15, 155 rides") + the
  load-log expander (below).

Window bounds come from the dataset's own clock (`date_bounds()`), not the
wall clock — a static fixture or stale sync must still render sensibly.
Wall-clock windows (KPI-style "this week") are the documented exception.

## The four states — every component, no exceptions

1. **Success**: chart + caption.
2. **Empty**: `st.info("No rides for **Road** in the selected window")` —
   name the active filter, never a bare zero, never a blank cell.
3. **Error**: one `_run_query(key, fn, *args)` helper wraps every data call:
   logs `(key, ms, rows)` to `st.session_state.load_log`, on exception logs
   `rows=-1`, renders `st.error(f"{key}: {exc}")`, and the app keeps
   rendering. A component failing must never kill the page.
4. **Loading**: Streamlit's own spinners (`@st.cache_data` shows them).

The **load log** — `key | ms | rows`, failures included — renders in a
collapsed footer expander as a small table. It is §diagnostics *and* the
handover vocabulary: component keys are stable identifiers
(`weekly_distance`, `power_zones`) that you and the user quote in change
requests. The AppTest gate asserts on it.

## Cross-filter (donut → everything else)

- Source chart (typically a mix donut) queries **date-only** so it stays
  stable while its selection filters the others.
- `st.plotly_chart(..., on_select="rerun", selection_mode=("points",))`;
  read `sel.selection.points[0].customdata` for the category; guard the whole
  read in `try/except` (selection events don't fire in every context).
- Selection → `st.session_state["focus_<type>"]`; when it changes
  **rerun unconditionally** (also on clear — a stale banner that only
  disappears on the *next* interaction is a recorded bug class).
- A banner above the filtered section (`st.info`) + a **Clear** button +
  `st.rerun()`.
- The sidebar multiselect must mirror the same dimension so the cross-filter
  always has a keyboard/widget path (a11y: never pointer-only).
- AppTest cannot click plotly marks: test focus by pre-seeding
  `session_state` and rerunning, and remember an empty AppTest selection is
  indistinguishable from deselection.

## Formatting (pin the obvious ones; consistency beats cleverness)

distances/km 1 dp · speeds km/h 1 dp · ratios (IF, W/kg) 2 dp · counts int ·
hours 1 dp · percents 1 dp with explicit sign · ranges in labels use
en-dashes (`75–85`) · tabular numerals in tables (`st.dataframe`).
Deltas: period comparisons with matching precision, and say vs what.

## Accessibility floor

- **Never color alone**: multi-series charts get shape (markers vs lines) or
  dash patterns plus legend labels; diverging series (e.g. form/TSB) split
  into positive/negative traces with distinct names.
- Every pointer interaction has a widget path (multiselect ↔ donut).
- Legends + captions carry the definitions and the qualifying counts
  ("10 rides with power in window") so readers can judge the data behind
  every number.
- Night mode must re-theme charts *and* respect the token contract — check
  `st.info`/alert chrome contrast when the repo's `page_css` doesn't cover it
  (known tech-debt class; log it in the worklog if present).

## What "finished" looks like

Empty window → friendly banner + every cell an informative `st.info`.
Type filter narrowed to a category absent from the window → empty states that
name it. Feature constant unset (e.g. no FTP) → the dependent sections show
the "not configured" state with the env-var remedy, everything else renders.
Server down at first paint → one clear `st.error` + `st.stop()`, not a
traceback wall. Every one of these is an AppTest scenario, not a hope.
