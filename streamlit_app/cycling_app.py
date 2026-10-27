"""Cycling analytics — Streamlit edition (docs/cycling-app-spec.md).

One-page cycling dashboard over the intervals.icu warehouse: fitness & load,
volume & consistency, power, speed & cadence, endurance & terrain. Renders
DataFrames from the live AQL data layer (cycling_queries_aql); computes
nothing itself. Every data call goes through ``_run_query`` which logs
(key, ms, rows) to ``st.session_state.load_log`` — the diagnostics expander
in the footer. The C5 donut is the cross-filter source (click a slice to
focus a ride type; the sidebar multiselect mirrors it for keyboard access).

Run:  ANFRA_MCP_URL=http://127.0.0.1:7879/mcp uv run streamlit run streamlit_app/cycling_app.py
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go

# Import bootstrap: repo root must be on sys.path before anfra_client imports
# (Streamlit only puts the script's own folder there).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cycling_queries_aql as q  # noqa: E402
import streamlit as st  # noqa: E402
from theme import (  # noqa: E402
    DARK,
    LIGHT,
    RIDE_LABELS,
    RIDE_ORDER,
    apply_layout,
    page_css,
    palette,
    ride_color,
)

st.set_page_config(
    page_title="Cycling Analytics",
    page_icon="🚴",
    layout="wide",
    initial_sidebar_state="expanded",
)

DECOUPLING_ALARM_PCT = 8.0  # spec §6.3: drift > +8% = warm alarm


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------


def get_theme() -> dict[str, Any]:
    if "night" not in st.session_state:
        st.session_state.night = False
    return DARK if st.session_state.night else LIGHT


theme = get_theme()
st.markdown(page_css(theme), unsafe_allow_html=True)

CAT = palette(theme)
POS, NEG = theme["pos"], theme["neg"]


# --------------------------------------------------------------------------
# Load-log query wrapper
# --------------------------------------------------------------------------


def _run_query(key: str, fn: Callable[..., Any], *args: Any) -> Any:
    """Call a data-layer fn, log (key, ms, rows) to the footer load log.

    On failure: logs rows=-1, renders st.error, keeps rendering the page.
    Return type is deliberately loose (DataFrame | tuple | None) to mirror
    the untyped app-layer style of app.py.
    """
    log: list[tuple[str, float, int]] = st.session_state.setdefault("load_log", [])
    t0 = time.perf_counter()
    try:
        df = fn(*args)
    except Exception as exc:  # noqa: BLE001 — the page must keep rendering
        log.append((key, round((time.perf_counter() - t0) * 1000, 1), -1))
        st.error(f"“{key}” failed to load: {exc}")
        return None
    log.append((key, round((time.perf_counter() - t0) * 1000, 1), len(df)))
    return df


def _num(v: Any, fallback: float = 0.0) -> float:
    """NaN/None-safe float (never 0-for-missing in aggregates that matter)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return fallback
    return float(v)


# --------------------------------------------------------------------------
# Sidebar controls
# --------------------------------------------------------------------------

with st.sidebar:
    st.header("🚴 Cycling Analytics")
    st.caption("intervals.icu · DuckDB · Great Wave")

    if st.button(
        "🌙 Switch to night" if not st.session_state.night else "☀️ Switch to day",
        width="stretch",
    ):
        st.session_state.night = not st.session_state.night
        st.rerun()

    st.divider()

    bounds = _run_query("date_bounds", q.date_bounds)
    min_date = max_date = dt.date.today()
    if bounds is not None:
        min_date, max_date = bounds

    preset = st.radio(
        "Date range",
        ["Last 30 days", "Last 90 days", "Year to date", "All time"],
        index=1,
    )
    if preset == "Last 30 days":
        default_range = (max_date - dt.timedelta(days=29), max_date)
    elif preset == "Last 90 days":
        default_range = (max_date - dt.timedelta(days=89), max_date)
    elif preset == "Year to date":
        default_range = (dt.date(max_date.year, 1, 1), max_date)
    else:
        default_range = (min_date, max_date)

    if st.session_state.get("prev_preset") != preset:
        st.session_state.prev_preset = preset
        st.session_state.date_range = default_range

    date_range = st.date_input(
        "Dates",
        value=st.session_state.get("date_range", default_range),
        min_value=min_date,
        max_value=max_date,
        key="date_range",
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        date_from, date_to = (d.isoformat() for d in date_range)
    else:
        date_from, date_to = default_range[0].isoformat(), default_range[1].isoformat()

    st.divider()

    selected_types = tuple(
        st.multiselect(
            "Ride types",
            RIDE_ORDER,
            format_func=lambda r: RIDE_LABELS.get(r, r),
            placeholder="All ride types",
            key="ride_types",
        )
    )

    st.divider()
    st.caption(
        "Data: live AQL over `data/running.duckdb` via `anfra serve`. "
        "Rebuild with `python3 scripts/sync_intervals_icu.py --build-only`."
    )


# --------------------------------------------------------------------------
# Ride-type cross-filter (C5 donut is the source)
# --------------------------------------------------------------------------

focus_ride_type: str | None = st.session_state.get("focus_ride_type")
effective_types = (focus_ride_type,) if focus_ride_type else selected_types
filter_desc = (
    f"**{RIDE_LABELS.get(focus_ride_type, focus_ride_type)}** (cross-filter)"
    if focus_ride_type
    else (
        ", ".join(RIDE_LABELS.get(t, t) for t in selected_types) if selected_types else "all types"
    )
)


def _empty(key: str, what: str = "rides") -> None:
    st.info(f"No {what} in this window for the selected types ({filter_desc}) — “{key}”.")


# --------------------------------------------------------------------------
# Header + KPI strip (K1–K4)
# --------------------------------------------------------------------------

st.title("Cycling Analytics")
st.caption(
    "Fitness · volume · power · speed · terrain — all rides, split by type. "
    "Click the donut to cross-filter a ride type."
)

ftp_df = _run_query("kpi_ftp", q.kpi_ftp)
week_df = _run_query("kpi_ride_km_week", q.kpi_ride_km_week, effective_types)
elev_df = _run_query("kpi_elev_90d", q.kpi_elev_90d, effective_types)
if_df = _run_query("kpi_if_90d", q.kpi_if_90d, effective_types)

c1, c2, c3, c4 = st.columns(4)

ftp_row = ftp_df.iloc[0] if ftp_df is not None and len(ftp_df) else None
if ftp_row is not None:
    c1.metric(
        "Current FTP",
        f"{int(_num(ftp_row['ftp_w']))} W",
        delta="used for %FTP & IF",
        delta_color="off",
    )
else:
    c1.metric("Current FTP", "FTP not configured", delta="set CYCLING_FTP_WATTS", delta_color="off")

if week_df is not None and len(week_df):
    this_week = _num(week_df["this_week_km"].iloc[0])
    avg_4wk = _num(week_df["avg_4wk_km"].iloc[0])
    c2.metric(
        "Ride km this week",
        f"{this_week:.1f} km",
        delta=f"{this_week - avg_4wk:+.1f} vs 4-wk mean ({avg_4wk:.1f})",
        delta_color="normal",
    )
else:
    c2.metric("Ride km this week", "—", delta="no rides yet", delta_color="off")

if elev_df is not None and len(elev_df) and not pd.isna(elev_df["elev_gain_m"].iloc[0]):
    e_row = elev_df.iloc[0]
    c3.metric(
        "Elevation, last 90 days",
        f"{int(_num(e_row['elev_gain_m'])):,} m",
        delta=f"{_num(e_row['km']):,.1f} km ridden",
        delta_color="off",
    )
else:
    c3.metric("Elevation, last 90 days", "—", delta="no outdoor rides", delta_color="off")

if_row = if_df.iloc[0] if if_df is not None and len(if_df) else None
if if_row is not None and _num(if_row["rides_with_power"]) > 0 and not pd.isna(if_row["if_mean"]):
    c4.metric(
        "Intensity, last 90 days",
        f"{_num(if_row['if_mean']):.2f} IF",
        delta=f"{int(_num(if_row['rides_with_power']))} rides with power",
        delta_color="off",
    )
else:
    c4.metric("Intensity, last 90 days", "—", delta="no power rides", delta_color="off")

st.divider()


# --------------------------------------------------------------------------
# Chart helpers
# --------------------------------------------------------------------------


def section(title: str, caption: str) -> None:
    st.header(title)
    st.markdown(f'<div class="wave-caption">{caption}</div>', unsafe_allow_html=True)


def line(
    x: Any, y: Any, name: str, color: str, dash: str | None = None, yaxis: str = "y"
) -> go.Scatter:
    return go.Scatter(
        x=x,
        y=y,
        name=name,
        mode="lines",
        line=dict(color=color, dash=dash, width=2),
        yaxis=yaxis,
    )


_pending: list[tuple[go.Figure, pd.DataFrame, str] | None] = []


def queue(fig: go.Figure, df: pd.DataFrame | None, key: str) -> None:
    """Stage a chart for grid rendering (mirrors the anfra grid)."""
    _pending.append((fig, df, key) if df is not None and len(df) else None)


def _render_cell(cell: tuple[go.Figure, pd.DataFrame, str] | None) -> None:
    if cell is None:
        _empty("chart")
        return
    fig, _, key = cell
    st.plotly_chart(fig, width="stretch", key=key)


def flush_row(count: int) -> None:
    """Render queued charts in a row of `count` cells; empty cells show info."""
    cols = st.columns(count)
    for col in cols:
        cell = _pending.pop(0) if _pending else None
        with col:
            _render_cell(cell)


# --------------------------------------------------------------------------
# Fitness & load (C1, C2) — date-only, athlete-level
# --------------------------------------------------------------------------

section(
    "Fitness & load",
    "CTL/ATL/TSB are athlete-level (all sports, weekly summaries, full history "
    "→ window end). Cycling load = weekly 'Ride' category load.",
)

ft = _run_query("fitness_trend", q.fitness_trend, date_from, date_to)
if ft is not None and len(ft):
    fig = go.Figure()
    fig.add_trace(line(ft["week_start"], ft["ctl"], "CTL (fitness)", CAT[0]))
    fig.add_trace(line(ft["week_start"], ft["atl"], "ATL (fatigue)", CAT[3]))
    tsb = ft["tsb"]
    fig.add_trace(
        line(
            ft["week_start"],
            [v if v >= 0 else None for v in tsb],
            "TSB (fresh)",
            POS,
            dash="dot",
            yaxis="y2",
        )
    )
    fig.add_trace(
        line(
            ft["week_start"],
            [v if v < 0 else None for v in tsb],
            "TSB (fatigue)",
            NEG,
            dash="dot",
            yaxis="y2",
        )
    )
    fig.update_layout(
        yaxis=dict(title="CTL / ATL"),
        yaxis2=dict(
            title="TSB", overlaying="y", side="right", zeroline=True, zerolinecolor=theme["grid"]
        ),
        hovermode="x unified",
    )
    queue(apply_layout(fig, theme, "Fitness trend — CTL · ATL · TSB (weekly)"), ft, "fitness_trend")

lr = _run_query("weekly_load_ramp", q.weekly_load_ramp, date_from, date_to)
if lr is not None and len(lr):
    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=lr["week_start"], y=lr["load"], name="Load", marker_color=CAT[0], opacity=0.85)
    )
    fig.add_trace(line(lr["week_start"], lr["ramp"], "Ramp (Δ vs prior week)", CAT[1], yaxis="y2"))
    fig.add_hline(y=0, line_color=NEG, line_dash="dot", line_width=1)
    fig.update_layout(
        yaxis=dict(title="Weekly cycling load"),
        yaxis2=dict(title="Ramp", overlaying="y", side="right"),
        barmode="overlay",
    )
    queue(apply_layout(fig, theme, "Weekly cycling load & ramp"), lr, "weekly_load_ramp")

flush_row(2)

# --------------------------------------------------------------------------
# Volume & consistency (C3, C4 | C5 donut, C6) — C5 is the cross-filter source
# --------------------------------------------------------------------------

section(
    "Volume & consistency",
    "Ride volume from activity records (power-era detail from Oct 2024; earlier "
    "weeks may be sparse). Long ride = moving time ≥ 75 min.",
)

wr = _run_query("weekly_ride_distance", q.weekly_ride_distance, date_from, date_to)
if wr is not None and len(wr):
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=wr["week_start"], y=wr["ride_km"], name="Ride km", marker_color=CAT[3], opacity=0.9
        )
    )
    fig.add_trace(
        line(wr["week_start"], wr["elev_gain_m"], "Elevation gain (m)", CAT[2], yaxis="y2")
    )
    fig.update_layout(
        yaxis=dict(title="km"),
        yaxis2=dict(title="Elevation (m)", overlaying="y", side="right"),
    )
    queue(apply_layout(fig, theme, "Weekly ride distance & elevation"), wr, "weekly_ride_distance")

cal = _run_query("ride_calendar", q.ride_calendar, date_from, date_to)
if cal is not None and len(cal):
    days = pd.to_datetime(cal["day"])
    weeks = pd.date_range(days.min().to_period("W-MON").start_time, days.max(), freq="W-MON")
    pivot = cal.assign(week=days.dt.to_period("W-MON").dt.start_time).pivot_table(
        index=days.dt.day_of_week, columns="week", values="km", aggfunc="sum"
    )
    pivot = pivot.reindex(index=range(7), columns=pd.DatetimeIndex(weeks))
    # month labels: label a week with its month when it is the first of that month
    labels: list[str] = []
    seen: set[int] = set()
    cols = [pd.Timestamp(w) for w in pivot.columns]
    for i, ts in enumerate(cols):
        if ts.month not in seen or i == 0:
            seen.add(ts.month)
            labels.append(ts.strftime("%b %d"))
        else:
            labels.append(ts.strftime("%d"))
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=labels,
            y=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            colorscale=theme["heatmap"],
            xgap=2,
            ygap=2,
            hovertemplate="%{y}: %{z:.1f} km<extra></extra>",
            colorbar=dict(title="km", thickness=10, len=0.6),
        )
    )
    queue(apply_layout(fig, theme, "Daily ride distance — calendar heatmap"), cal, "ride_calendar")

mix = _run_query("ride_mix", q.ride_mix, date_from, date_to)
donut = None
if mix is not None and len(mix):
    mix = mix.sort_values("hours", ascending=False)  # desc from 12 o'clock
    fig = go.Figure(
        go.Pie(
            labels=[RIDE_LABELS.get(r, r) for r in mix["ride_type"]],
            values=mix["hours"],
            customdata=mix["ride_type"],
            hole=0.6,
            sort=False,
            marker=dict(
                colors=[ride_color(theme, r) for r in mix["ride_type"]],
                line=dict(color=theme["card"], width=1),
            ),
            hovertemplate="%{label}: %{value:.1f} h<extra></extra>",
        )
    )
    donut = apply_layout(fig, theme, "Hours by ride type — click a slice to cross-filter")

wh = _run_query("weekly_hours_by_type", q.weekly_hours_by_type, date_from, date_to)
if wh is not None and len(wh):
    pivot = wh.pivot_table(
        index="week_start", columns="ride_type", values="hours", aggfunc="sum"
    ).fillna(0)
    totals = pivot.sum(axis=1)
    fig = go.Figure()
    for rt in RIDE_ORDER:
        if rt in pivot.columns:
            share = (pivot[rt] / totals * 100.0).round(1)
            fig.add_trace(
                go.Bar(
                    x=pivot.index,
                    y=pivot[rt],
                    name=RIDE_LABELS.get(rt, rt),
                    marker_color=ride_color(theme, rt),
                    customdata=share,
                    hovertemplate="%{y:.1f} h · %{customdata:.1f}%<extra>"
                    + RIDE_LABELS.get(rt, rt)
                    + "</extra>",
                )
            )
    fig.update_layout(barmode="stack", hovermode="x unified")
    queue(
        apply_layout(fig, theme, "Weekly hours by ride type (stacked)"), wh, "weekly_hours_by_type"
    )

# grid row: weekly distance | donut (cross-filter source)
left, right = st.columns(2)
with left:
    _render_cell(_pending.pop(0) if _pending else None)
with right:
    if donut is not None:
        sel = st.plotly_chart(
            donut,
            width="stretch",
            on_select="rerun",
            selection_mode=("points",),
            key="ride_mix",
        )
        picked = None
        try:
            pts = sel.selection.points if sel and sel.selection else []
            if pts:
                picked = pts[0].customdata  # type: ignore[attr-defined]
        except (AttributeError, KeyError, TypeError):
            picked = None
        if picked != focus_ride_type:
            st.session_state.focus_ride_type = picked
            if picked:
                st.rerun()
        if focus_ride_type:
            st.info(
                f"Cross-filter active: **{RIDE_LABELS.get(focus_ride_type, focus_ride_type)}** "
                "— weekly summaries and fitness stay unfiltered; click the slice "
                "again or press clear to reset."
            )
            if st.button("Clear cross-filter"):
                st.session_state.focus_ride_type = None
                st.rerun()
    else:
        _empty("ride_mix")

# grid row: calendar heatmap | weekly hours
flush_row(2)

# --------------------------------------------------------------------------
# Power (C7, C8 | C9 full width) — type-filtered, FTP-referenced
# --------------------------------------------------------------------------

section(
    "Power",
    "Power metrics reference each ride's FTP (per-activity where recorded). "
    "Power data is dense only from Oct 2024 — captions carry qualifying counts.",
)

rp = _run_query("rides_with_power", q.rides_with_power, date_from, date_to, effective_types)
with_power = int(_num(rp["with_power"].iloc[0], 0)) if rp is not None and len(rp) else 0
total_rides = int(_num(rp["total"].iloc[0], 0)) if rp is not None and len(rp) else 0

pz = _run_query("power_zones_weekly", q.power_zones_weekly, date_from, date_to, effective_types)
if pz is not None and len(pz):
    pivot = pz.pivot_table(
        index="week_start", columns="zone", values="hours", aggfunc="sum"
    ).fillna(0)
    fig = go.Figure()
    for i, zone in enumerate(q.FTP_ZONE_LABELS):
        if zone in pivot.columns:
            fig.add_trace(
                go.Bar(
                    x=pivot.index,
                    y=pivot[zone],
                    name=zone,
                    marker_color=CAT[i % len(CAT)],
                )
            )
    fig.update_layout(barmode="stack", hovermode="x unified")
    queue(
        apply_layout(
            fig,
            theme,
            f"Weekly hours by %FTP zone ({with_power} of {total_rides} rides with power)",
        ),
        pz,
        "power_zones_weekly",
    )

it = _run_query("intensity_trend", q.intensity_trend, date_from, date_to, effective_types)
if it is not None and len(it):
    fig = go.Figure()
    fig.add_trace(line(it["month"], it["if_mean"], "Intensity factor", CAT[0]))
    if "pct_ftp" in it.columns:
        fig.add_trace(line(it["month"], it["pct_ftp"], "Mean %FTP", CAT[2], dash="dot", yaxis="y2"))
    fig.update_layout(
        yaxis=dict(title="IF"),
        yaxis2=dict(title="%FTP", overlaying="y", side="right"),
        hovermode="x unified",
    )
    queue(
        apply_layout(
            fig,
            theme,
            f"Monthly intensity — duration-weighted IF ({with_power} rides with power)",
        ),
        it,
        "intensity_trend",
    )

flush_row(2)

pw = _run_query("power_weight_weekly", q.power_weight_weekly, date_from, date_to, effective_types)
if pw is not None and len(pw):
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=pw["week_start"],
            y=pw["watts"],
            name="Mean weighted watts",
            marker_color=CAT[0],
            opacity=0.85,
            hovertemplate="%{x}: %{y:.0f} W<extra></extra>",
        )
    )
    fig.add_trace(line(pw["week_start"], pw["w_per_kg"], "W/kg", CAT[2], dash="dot", yaxis="y2"))
    fig.update_layout(
        yaxis=dict(title="Watts"),
        yaxis2=dict(title="W/kg", overlaying="y", side="right"),
        barmode="overlay",
    )
    queue(
        apply_layout(
            fig,
            theme,
            "Weekly mean weighted power & W/kg (weeks without power gap)",
        ),
        pw,
        "power_weight_weekly",
    )

flush_row(1)

# --------------------------------------------------------------------------
# Speed & cadence (C10, C11 | C12, C13 | C14, C15) — type-filtered
# --------------------------------------------------------------------------

section(
    "Speed & cadence",
    "Monthly per-type aggregates. Speed = total distance / total moving time; "
    "cadence-weighted means exclude coast artifacts (≤40 rpm). Virtual trainer "
    "rides record power but no GPS distance.",
)


def _by_type_lines(df: pd.DataFrame, ycol: str, title: str, ytitle: str, key: str) -> None:
    fig = go.Figure()
    for rt in RIDE_ORDER:
        sub = df[df["ride_type"] == rt]
        if len(sub):
            fig.add_trace(
                line(sub["month"], sub[ycol], RIDE_LABELS.get(rt, rt), ride_color(theme, rt))
            )
    fig.update_layout(yaxis=dict(title=ytitle), hovermode="x unified")
    queue(apply_layout(fig, theme, title), df, key)


sp = _run_query(
    "speed_by_type_monthly", q.speed_by_type_monthly, date_from, date_to, effective_types
)
if sp is not None:
    _by_type_lines(
        sp,
        "speed_kmh",
        "Monthly avg speed by type (km/h)",
        "km/h",
        "speed_by_type_monthly",
    )

cd = _run_query(
    "cadence_by_type_monthly", q.cadence_by_type_monthly, date_from, date_to, effective_types
)
if cd is not None:
    _by_type_lines(
        cd,
        "rpm",
        "Monthly weighted cadence by type (rpm)",
        "rpm",
        "cadence_by_type_monthly",
    )

flush_row(2)

cb = _run_query(
    "cadence_buckets_weekly", q.cadence_buckets_weekly, date_from, date_to, effective_types
)
if cb is not None and len(cb):
    pivot = cb.pivot_table(
        index="week_start", columns="bucket", values="hours", aggfunc="sum"
    ).fillna(0)
    fig = go.Figure()
    for i, bucket in enumerate(q.CADENCE_BUCKETS):
        if bucket in pivot.columns:
            fig.add_trace(
                go.Bar(
                    x=pivot.index,
                    y=pivot[bucket],
                    name=bucket,
                    marker_color=CAT[i % len(CAT)],
                )
            )
    fig.update_layout(barmode="stack", hovermode="x unified")
    queue(
        apply_layout(
            fig,
            theme,
            f"Weekly hours by cadence bucket (avg > {q.CADENCE_MIN_RPM} rpm)",
        ),
        cb,
        "cadence_buckets_weekly",
    )

sc = _run_query("cadence_vs_speed", q.cadence_vs_speed, date_from, date_to, effective_types)
if sc is not None and len(sc):
    fig = go.Figure()
    for rt in RIDE_ORDER:
        sub = sc[sc["ride_type"] == rt]
        if len(sub):
            fig.add_trace(
                go.Scatter(
                    x=sub["cadence"],
                    y=sub["speed_kmh"],
                    name=RIDE_LABELS.get(rt, rt),
                    mode="markers",
                    marker=dict(color=ride_color(theme, rt), size=8, opacity=0.75, symbol="circle"),
                    customdata=list(zip(sub["name"], sub["day"], strict=True)),
                    hovertemplate="%{customdata[0]}<br>%{customdata[1]}: "
                    "%{y:.1f} km/h @ %{x:.0f} rpm<extra>" + RIDE_LABELS.get(rt, rt) + "</extra>",
                )
            )
    fig.update_layout(
        xaxis=dict(title="Cadence (rpm)"),
        yaxis=dict(title="Speed (km/h)"),
    )
    queue(apply_layout(fig, theme, "Speed vs cadence, per ride", 340), sc, "cadence_vs_speed")

flush_row(2)

hl = _run_query(
    "hilliness_by_type_monthly", q.hilliness_by_type_monthly, date_from, date_to, effective_types
)
if hl is not None:
    _by_type_lines(
        hl,
        "elev_per_km",
        "Monthly hilliness by type (m climbed per km)",
        "m/km",
        "hilliness_by_type_monthly",
    )

tp = _run_query("speed_by_temp", q.speed_by_temp, date_from, date_to, effective_types)
if tp is not None and len(tp):
    labels = [f"{int(v)}–{int(v + q.TEMP_BUCKET_STEP_C)} °C" for v in tp["bucket_low"]]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=tp["speed_kmh"],
            customdata=tp["rides"],
            marker_color=CAT[1],
            hovertemplate="%{x}: %{y:.1f} km/h · %{customdata} rides<extra></extra>",
        )
    )
    fig.update_layout(yaxis=dict(title="km/h"))
    queue(
        apply_layout(
            fig,
            theme,
            "Speed by temperature bucket (warm buckets = fewer, faster rides)",
        ),
        tp,
        "speed_by_temp",
    )

flush_row(2)

# --------------------------------------------------------------------------
# Endurance & terrain (C16, C17) — date-only
# --------------------------------------------------------------------------

section(
    "Endurance & terrain",
    "HR decoupling on long rides (moving time ≥ 75 min, computed locally from "
    "streams; positive = HR drift). Weekly summaries stay unfiltered by type.",
)

ld = _run_query("long_ride_decoupling", q.long_ride_decoupling, date_from, date_to)
if ld is not None and len(ld):
    colors = [NEG if v > DECOUPLING_ALARM_PCT else POS for v in ld["decoupling_pct"]]
    fig = go.Figure(
        go.Scatter(
            x=ld["day"],
            y=ld["decoupling_pct"],
            mode="markers",
            name="Long ride",
            marker=dict(color=colors, size=9, opacity=0.85, symbol="circle"),
            customdata=ld["name"],
            hovertemplate="%{customdata}<br>%{x}: %{y:+.1f}%<extra></extra>",
        )
    )
    avg = _num(ld["decoupling_pct"].mean())
    fig.add_hline(
        y=avg,
        line_color=theme["ink"],
        line_dash="dash",
        line_width=1,
        annotation_text=f"avg {avg:+.1f}%",
    )
    fig.add_hline(
        y=DECOUPLING_ALARM_PCT,
        line_color=NEG,
        line_dash="dot",
        line_width=1,
        annotation_text=f"drift > +{DECOUPLING_ALARM_PCT:.0f}%",
        annotation_position="top right",
    )
    fig.update_layout(yaxis=dict(title="Decoupling (%)"))
    queue(
        apply_layout(
            fig,
            theme,
            "HR decoupling on long rides (dots turn warm above +8% drift)",
        ),
        ld,
        "long_ride_decoupling",
    )

dc = _run_query("decoupling_by_type", q.decoupling_by_type, date_from, date_to)
if dc is not None and len(dc):
    fig = go.Figure(
        go.Bar(
            x=[RIDE_LABELS.get(r, r) for r in dc["ride_type"]],
            y=dc["avg_decoupling"],
            customdata=dc["long_rides"],
            marker_color=[ride_color(theme, r) for r in dc["ride_type"]],
            hovertemplate="%{x}: %{y:+.1f}% avg · %{customdata} long rides<extra></extra>",
        )
    )
    fig.update_layout(yaxis=dict(title="Decoupling (%)"))
    queue(
        apply_layout(fig, theme, "Mean HR decoupling by type (long rides)"),
        dc,
        "decoupling_by_type",
    )

flush_row(2)

# --------------------------------------------------------------------------
# Footer: data currency + load log
# --------------------------------------------------------------------------

st.divider()
st.caption(
    f"Data through **{max_date.isoformat()}** (latest ride; window "
    f"{date_from} → {date_to}). Fitness/load metrics span all sports at the "
    "athlete level; per-ride detail is dense from Oct 2024."
)

with st.expander("Query load log", expanded=False):
    log = st.session_state.get("load_log", [])
    if log:
        st.table(pd.DataFrame(log, columns=["query", "ms", "rows"]).set_index("query"))
    else:
        st.caption("No queries logged this session.")
