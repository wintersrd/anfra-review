"""Running & training analytics — Streamlit edition.

Streamlit port of the anfra dashboard (apps/running.html): same DuckDB data
(reader snapshot), same 21-query surface, Great Wave styling, day/night toggle,
and sport cross-filtering via native Plotly selection events.

Run:  uv run streamlit run streamlit_app/app.py
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import queries as q
from theme import (
    DARK,
    LIGHT,
    SURFACE_ORDER,
    SPORT_LABELS,
    apply_layout,
    page_css,
    palette,
    surface_color,
)

st.set_page_config(
    page_title="Running Analytics",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------


def get_theme() -> dict:
    if "night" not in st.session_state:
        st.session_state.night = False
    return DARK if st.session_state.night else LIGHT


theme = get_theme()
st.markdown(page_css(theme), unsafe_allow_html=True)

CAT = palette(theme)
POS, NEG = theme["pos"], theme["neg"]


# --------------------------------------------------------------------------
# Sidebar controls
# --------------------------------------------------------------------------

with st.sidebar:
    st.header("🌊 Running Analytics")
    st.caption("intervals.icu · DuckDB · Great Wave")

    if st.button(
        "🌙 Switch to night" if not st.session_state.night else "☀️ Switch to day",
        width="stretch",
    ):
        st.session_state.night = not st.session_state.night
        st.rerun()

    st.divider()

    min_date, max_date = q.date_bounds()
    preset = st.radio(
        "Date range",
        ["Last 30 days", "Last 90 days", "Year to date", "All time"],
        index=1,
    )
    today = max_date
    if preset == "Last 30 days":
        default_range = (today - dt.timedelta(days=29), today)
    elif preset == "Last 90 days":
        default_range = (today - dt.timedelta(days=89), today)
    elif preset == "Year to date":
        default_range = (dt.date(today.year, 1, 1), today)
    else:
        default_range = (min_date, today)

    if "prev_preset" not in st.session_state or st.session_state.prev_preset != preset:
        st.session_state.prev_preset = preset
        st.session_state.date_range = default_range

    date_range = st.date_input(
        "Dates",
        value=st.session_state.get("date_range", default_range),
        min_value=min_date,
        max_value=today,
        key="date_range",
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        date_from, date_to = (d.isoformat() for d in date_range)
    else:
        date_from, date_to = default_range[0].isoformat(), default_range[1].isoformat()

    st.divider()

    all_sports = ["run", "ride", "walk", "strength", "yoga", "row", "other"]
    sports = tuple(
        st.multiselect(
            "Sports",
            all_sports,
            format_func=lambda s: SPORT_LABELS.get(s, s),
            placeholder="All sports",
        )
    )
    surfaces = tuple(
        st.multiselect(
            "Run surfaces",
            SURFACE_ORDER,
            format_func=lambda s: s.capitalize(),
            placeholder="All surfaces",
        )
    )

    st.divider()
    st.caption(
        "Data: `data/running_reader.duckdb` (snapshot). Rebuild with "
        "`python3 scripts/sync_intervals_icu.py --build-only`."
    )


# --------------------------------------------------------------------------
# Sport cross-filter (click a sport-mix slice)
# --------------------------------------------------------------------------

focus_sport: str | None = st.session_state.get("focus_sport")
effective_sports = (focus_sport,) if focus_sport else sports


def _run_query(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.stop()


# --------------------------------------------------------------------------
# KPI strip
# --------------------------------------------------------------------------

st.title("Running & Training Analytics")
st.caption(
    "Fitness · volume · speed · stride · decoupling · environment — all sports, "
    "run analytics split by surface."
)

fit_df = _run_query(q.kpi_fitness)
fit = fit_df.iloc[0] if len(fit_df) else None
week = _run_query(q.kpi_week_distance, effective_sports, surfaces)
kpi_90d = _run_query(q.kpi_90d, effective_sports)
dec = _run_query(q.kpi_decoupling).iloc[0]

c1, c2, c3, c4 = st.columns(4)
if fit is not None:
    tsb_val = float(fit["tsb"] or 0.0)
    c1.metric(
        "CTL / ATL / TSB (latest week)",
        f"{float(fit['ctl'] or 0):.0f} / {float(fit['atl'] or 0):.0f} / {tsb_val:+.0f}",
        delta=f"{'fresh' if tsb_val >= 0 else 'fatigued'}",
        delta_color="off" if tsb_val < 0 else "normal",
    )
this_week = float(week["this_week_km"].iloc[0] or 0) if len(week) else 0.0
avg_4wk = float(week["avg_4wk_km"].iloc[0] or 0) if len(week) else 0.0
c2.metric(
    "Run this week",
    f"{this_week:.1f} km",
    delta=f"{this_week - avg_4wk:+.1f} vs 4-wk avg ({avg_4wk:.1f})",
    delta_color="normal",
)
c3.metric(
    "Distance, last 90 days",
    f"{float(kpi_90d['km'].iloc[0] or 0):.0f} km",
    delta="all sports" if not focus_sport else SPORT_LABELS.get(focus_sport, focus_sport),
    delta_color="off",
)
if dec is not None and dec["avg_decoupling"] is not None:
    c4.metric(
        "HR decoupling, last 90 days",
        f"{float(dec['avg_decoupling']):+.1f}%",
        delta=f"{int(dec['long_runs'])} long runs",
        delta_color="off",
    )
else:
    c4.metric("HR decoupling, last 90 days", "—", delta="no long runs", delta_color="off")

st.divider()


# --------------------------------------------------------------------------
# Chart helpers
# --------------------------------------------------------------------------


def section(title: str, caption: str) -> None:
    st.header(title)
    st.markdown(f'<div class="wave-caption">{caption}</div>', unsafe_allow_html=True)


def line(
    x: list, y: list, name: str, color: str, dash: str | None = None, yaxis: str = "y"
) -> go.Scatter:
    return go.Scatter(
        x=x, y=y, name=name, mode="lines", line=dict(color=color, dash=dash, width=2),
        yaxis=yaxis,
    )


def empty_or(fig: go.Figure, df: pd.DataFrame, title: str) -> None:
    if df is None or len(df) == 0:
        st.info(f"No data for “{title}” in the selected window.")
        return
    st.plotly_chart(fig, width="stretch", key=title)


# --------------------------------------------------------------------------
# Fitness & load
# --------------------------------------------------------------------------

section("Fitness & load", "CTL/ATL/TSB and weekly load from intervals.icu weekly summaries (2012 → today).")

ft = _run_query(q.fitness_trend, date_from, date_to)
if len(ft):
    fig = go.Figure()
    fig.add_trace(line(ft["week_start"], ft["ctl"], "CTL (fitness)", CAT[0]))
    fig.add_trace(line(ft["week_start"], ft["atl"], "ATL (fatigue)", CAT[3]))
    tsb = ft["tsb"]
    fig.add_trace(
        line(ft["week_start"], [v if v >= 0 else None for v in tsb],
             "TSB (fresh)", POS, dash="dot", yaxis="y2")
    )
    fig.add_trace(
        line(ft["week_start"], [v if v < 0 else None for v in tsb],
             "TSB (fatigue)", NEG, dash="dot", yaxis="y2")
    )
    fig.update_layout(
        yaxis=dict(title="CTL / ATL"),
        yaxis2=dict(title="TSB", overlaying="y", side="right", zeroline=True,
                    zerolinecolor=theme["grid"]),
        hovermode="x unified",
    )
    empty_or(apply_layout(fig, theme, "Fitness trend — CTL · ATL · TSB (weekly)"), ft, "Fitness trend")
else:
    st.info("No weekly data in the selected window.")

lr = _run_query(q.load_ramp, date_from, date_to)
if len(lr):
    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=lr["week_start"], y=lr["load"], name="Load",
               marker_color=CAT[0], opacity=0.85)
    )
    fig.add_trace(
        line(lr["week_start"], lr["ramp_rate"], "Ramp rate", CAT[1], yaxis="y2")
    )
    fig.add_hline(y=0, line_color=NEG, line_dash="dot", line_width=1,
                  annotation_text="ramp guardrail", annotation_position="bottom right")
    fig.update_layout(
        yaxis=dict(title="Weekly load"),
        yaxis2=dict(title="Ramp rate", overlaying="y", side="right"),
        barmode="overlay",
    )
    empty_or(apply_layout(fig, theme, "Weekly load & ramp rate"), lr, "Weekly load")

# --------------------------------------------------------------------------
# Volume & consistency
# --------------------------------------------------------------------------

section("Volume & consistency", "Run volume from activity records (detail era, ~Oct 2024 →). Weekly all-sport mix spans the full summary history.")

wr = _run_query(q.weekly_run_distance, date_from, date_to, effective_sports, surfaces)
if len(wr):
    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=wr["week_start"], y=wr["run_km"], name="Run km",
               marker_color=CAT[3], opacity=0.9)
    )
    fig.add_trace(
        line(wr["week_start"], wr["elev_gain_m"], "Elevation gain (m)", CAT[2], yaxis="y2")
    )
    fig.update_layout(
        yaxis=dict(title="km"),
        yaxis2=dict(title="Elevation (m)", overlaying="y", side="right"),
    )
    empty_or(apply_layout(fig, theme, "Weekly run distance & elevation"), wr, "Weekly run distance")

dr = _run_query(q.daily_runs, date_from, date_to, effective_sports, surfaces)
if len(dr):
    days = pd.to_datetime(dr["day"])
    weeks = pd.date_range(days.min().to_period("W-SUN").start_time, days.max(), freq="W-SUN")
    pivot = dr.assign(week=days.dt.to_period("W-SUN").dt.start_time).pivot_table(
        index=days.dt.dayofweek, columns="week", values="km", aggfunc="sum"
    )
    pivot = pivot.reindex(columns=pd.DatetimeIndex(weeks))
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[d.strftime("%Y-%m-%d") for d in pivot.columns],
            y=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            colorscale=theme["heatmap"],
            xgap=2, ygap=2,
            hovertemplate="%{x} (%{y}): %{z:.1f} km<extra></extra>",
            colorbar=dict(title="km", thickness=10, len=0.6),
        )
    )
    empty_or(apply_layout(fig, theme, "Daily run distance — calendar heatmap"), dr, "Daily runs")

sm = _run_query(q.sport_mix, date_from, date_to)
if len(sm):
    fig = go.Figure(
        go.Pie(
            labels=[SPORT_LABELS.get(s, s) for s in sm["sport_group"]],
            values=sm["hours"],
            customdata=sm["sport_group"],
            hole=0.58,
            sort=False,
            marker=dict(
                colors=[CAT[i % len(CAT)] for i in range(len(sm))],
                line=dict(color=theme["card"], width=1),
            ),
            hovertemplate="%{label}: %{value:.1f} h<extra></extra>",
        )
    )
    sel = st.plotly_chart(
        apply_layout(fig, theme, "Hours by sport — click a slice to cross-filter"),
        width="stretch",
        on_select="rerun",
        selection_mode=("points",),
        key="sport_mix",
    )
    picked = None
    try:
        pts = sel.selection.points if sel and sel.selection else []
        if pts:
            picked = pts[0].customdata
    except (AttributeError, KeyError, TypeError):
        picked = None
    if picked != focus_sport:
        st.session_state.focus_sport = picked
        if picked:
            st.rerun()
    if focus_sport:
        st.info(
            f"Cross-filter active: **{SPORT_LABELS.get(focus_sport, focus_sport)}** "
            f"(click the slice again or press clear to reset)."
        )
        if st.button("Clear cross-filter"):
            st.session_state.focus_sport = None
            st.rerun()
else:
    st.info("No activities in the selected window.")

wc = _run_query(q.weekly_category, date_from, date_to)
if len(wc):
    order = wc.groupby("category")["hours"].sum().sort_values(ascending=False).index.tolist()
    pivot = wc.pivot_table(index="week_start", columns="category", values="hours", aggfunc="sum").fillna(0)
    fig = go.Figure()
    for i, cat in enumerate(order):
        if cat in pivot.columns:
            fig.add_trace(
                go.Bar(x=pivot.index, y=pivot[cat], name=SPORT_LABELS.get(cat, cat),
                       marker_color=CAT[i % len(CAT)])
            )
    fig.update_layout(barmode="stack", hovermode="x unified")
    empty_or(apply_layout(fig, theme, "Weekly hours by sport (stacked)"), wc, "Weekly hours")

# --------------------------------------------------------------------------
# Speed & progression
# --------------------------------------------------------------------------

section("Speed & progression", "Monthly aggregates, runs only. Pace = total moving time / distance; cadence in rpm (one foot).")

mp = _run_query(q.monthly_pace, date_from, date_to, effective_sports, surfaces)
if len(mp):
    fig = go.Figure(line(mp["month"], mp["pace_min_km"], "Pace", CAT[0]))
    fig.update_traces(hovertemplate="%{x|%Y-%m}: %{y:.2f} min/km<extra></extra>")
    empty_or(apply_layout(fig, theme, "Monthly run pace (min/km, lower is better)"), mp, "Monthly pace")

mc = _run_query(q.monthly_cadence, date_from, date_to, effective_sports, surfaces)
if len(mc):
    fig = go.Figure(line(mc["month"], mc["rpm"], "Cadence", CAT[6]))
    fig.update_traces(hovertemplate="%{x|%Y-%m}: %{y:.1f} rpm<extra></extra>")
    empty_or(apply_layout(fig, theme, "Monthly cadence (rpm)"), mc, "Monthly cadence")

me = _run_query(q.monthly_efficiency, date_from, date_to, effective_sports, surfaces)
if len(me):
    fig = go.Figure(line(me["month"], me["aerobic_efficiency"], "Aerobic efficiency", CAT[2]))
    fig.update_traces(hovertemplate="%{x|%Y-%m}: %{y:.3f} m/s per bpm<extra></extra>")
    empty_or(apply_layout(fig, theme, "Aerobic efficiency (m/s per bpm, higher is better)"), me, "Aerobic efficiency")

# --------------------------------------------------------------------------
# Surface & stride
# --------------------------------------------------------------------------

section("Surface & stride", "Road vs trail vs indoor. Stride = avg_speed·60/cadence, time-weighted; rows with suspect cadence (<40 rpm) are excluded upstream.")

sp = _run_query(q.surface_pace_trend, date_from, date_to, effective_sports, surfaces)
if len(sp):
    fig = go.Figure()
    for s in SURFACE_ORDER:
        sub = sp[sp["run_surface"] == s]
        if len(sub):
            fig.add_trace(line(sub["month"], sub["pace_min_km"], f"{s.capitalize()} pace",
                               surface_color(theme, s)))
    fig.update_layout(hovermode="x unified")
    empty_or(apply_layout(fig, theme, "Monthly pace by surface"), sp, "Pace by surface")

stt = _run_query(q.stride_trend, date_from, date_to, effective_sports, surfaces)
if len(stt):
    fig = go.Figure()
    for s in SURFACE_ORDER:
        sub = stt[stt["run_surface"] == s]
        if len(sub):
            fig.add_trace(line(sub["month"], sub["stride_m"], f"{s.capitalize()} stride",
                               surface_color(theme, s)))
    fig.update_layout(hovermode="x unified")
    empty_or(apply_layout(fig, theme, "Monthly stride length by surface (m)"), stt, "Stride trend")

ht = _run_query(q.hilliness_trend, date_from, date_to, effective_sports, surfaces)
if len(ht):
    fig = go.Figure()
    for s in SURFACE_ORDER:
        sub = ht[ht["run_surface"] == s]
        if len(sub):
            fig.add_trace(line(sub["month"], sub["elev_per_km"], f"{s.capitalize()} m/km",
                               surface_color(theme, s)))
    fig.update_layout(hovermode="x unified")
    empty_or(apply_layout(fig, theme, "Monthly elevation gain per km by surface"), ht, "Hilliness trend")

ds = _run_query(q.decoupling_by_surface, date_from, date_to)
if len(ds):
    fig = go.Figure(
        go.Bar(
            x=[s.capitalize() for s in ds["run_surface"]],
            y=ds["avg_decoupling"],
            customdata=ds["long_runs"],
            marker_color=[surface_color(theme, s) if s in SURFACE_ORDER else theme["muted"]
                          for s in ds["run_surface"]],
            hovertemplate="%{x}: %{y:.1f}% avg decoupling · %{customdata} long runs<extra></extra>",
        )
    )
    empty_or(apply_layout(fig, theme, "HR decoupling by surface (long runs)"), ds, "Decoupling by surface")

svp = _run_query(q.stride_vs_pace, date_from, date_to, effective_sports, surfaces)
if len(svp):
    fig = go.Figure()
    for s in SURFACE_ORDER:
        sub = svp[svp["run_surface"] == s]
        if len(sub):
            fig.add_trace(
                go.Scatter(
                    x=sub["pace_min_km"], y=sub["stride_m"], name=s.capitalize(),
                    mode="markers", marker=dict(color=surface_color(theme, s), size=7, opacity=0.75),
                    customdata=sub["name"],
                    hovertemplate="%{customdata}<br>%{x:.2f} min/km · %{y:.2f} m<extra>" + s + "</extra>",
                )
            )
    fig.update_layout(
        xaxis=dict(title="Pace (min/km)"), yaxis=dict(title="Stride (m)"),
    )
    empty_or(apply_layout(fig, theme, "Stride vs pace, per activity"), svp, "Stride vs pace")

# --------------------------------------------------------------------------
# Pace distribution
# --------------------------------------------------------------------------

section("Pace distribution", "Weekly running hours by average pace block. `unknown` = missing speed data.")

pb = _run_query(q.pace_blocks_weekly, date_from, date_to, effective_sports, surfaces)
if len(pb):
    bucket_colors = {
        "<4:00": CAT[3], "4\u20135": CAT[0], "5\u20136": CAT[6],
        "6\u20137": CAT[2], "7+": CAT[1], "unknown": CAT[7],
    }
    pivot = pb.pivot_table(index="week_start", columns="bucket", values="hours", aggfunc="sum").fillna(0)
    fig = go.Figure()
    for bucket in q.PACE_BUCKETS:
        if bucket in pivot.columns:
            fig.add_trace(
                go.Bar(x=pivot.index, y=pivot[bucket], name=bucket,
                       marker_color=bucket_colors[bucket])
            )
    fig.update_layout(barmode="stack", hovermode="x unified")
    empty_or(apply_layout(fig, theme, "Weekly hours by pace block (min/km)"), pb, "Pace blocks")

# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------

section("Environment", "HR decoupling on long runs (≥75 min, computed locally from streams) and pace vs recorded temperature.")

dt_df = _run_query(q.decoupling_trend, date_from, date_to)
if len(dt_df):
    fig = go.Figure(
        go.Scatter(
            x=dt_df["activity_start"], y=dt_df["decoupling_pct"], mode="markers",
            name="Long run", marker=dict(color=NEG, size=8, opacity=0.8),
            customdata=dt_df["name"],
            hovertemplate="%{customdata}<br>%{x|%Y-%m-%d}: %{y:+.1f}%<extra></extra>",
        )
    )
    avg = float(dt_df["decoupling_pct"].mean())
    fig.add_hline(y=avg, line_color=theme["ink"], line_dash="dash", line_width=1,
                  annotation_text=f"avg {avg:+.1f}%")
    fig.update_layout(yaxis=dict(title="Decoupling (%)"))
    empty_or(apply_layout(fig, theme, "HR decoupling trend (positive = HR drift / fatigue)"), dt_df, "Decoupling trend")

pt = _run_query(q.pace_by_temp, date_from, date_to, effective_sports, surfaces)
if len(pt):
    labels = [f"{int(v)}°C" for v in pt["bucket_low"]]
    fig = go.Figure(
        go.Bar(
            x=labels, y=pt["pace_min_km"], customdata=pt["runs"],
            marker_color=CAT[1],
            hovertemplate="%{x}: %{y:.2f} min/km · %{customdata} runs<extra></extra>",
        )
    )
    fig.update_layout(yaxis=dict(title="Pace (min/km)"))
    empty_or(apply_layout(fig, theme, "Pace by temperature (5°C buckets)"), pt, "Pace by temperature")

st.divider()
st.caption(
    "Scope notes: load/fitness metrics span all sports (weekly grain); volume/pace charts "
    "are run-only. Strava-era activities (2012–mid-2024) exist only as weekly aggregates. "
    "Streamlit port of the anfra app — see README."
)
