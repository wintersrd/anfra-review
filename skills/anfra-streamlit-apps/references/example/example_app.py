"""Example Streamlit app over the anfra semantic layer (skill template).

A complete miniature: import bootstrap, sidebar contract, KPI strip, two
components (line + cross-filter donut), four states, load log, footer.
ADAPT: rename, swap components — keep the patterns.
Run: ANFRA_MCP_URL=… uv run streamlit run streamlit_app/example_app.py
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from collections.abc import Callable
from pathlib import Path

# Import bootstrap — this folder AND the repo root must precede app imports.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import example_data_aql as data  # noqa: E402  the LIVE layer (never the oracle)
import pandas as pd  # noqa: E402  (must follow the sys.path bootstrap)
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402
from theme import (  # noqa: E402
    DARK,
    LIGHT,
    SURFACE_ORDER,
    apply_layout,
    page_css,
    surface_color,
)

PRESETS = ["Last 30 days", "Last 90 days", "Year to date", "All time"]
DEFAULT_WINDOW_DAYS = 90  # the spec's default preset


def _run_query(key: str, fn: Callable[..., pd.DataFrame], *args: object) -> pd.DataFrame:
    """Every data call goes through here: timed, logged, never fatal."""
    log = st.session_state.setdefault("load_log", [])
    t0 = time.perf_counter()
    try:
        df = fn(*args)
        log.append((key, round((time.perf_counter() - t0) * 1000), len(df)))
        return df
    except Exception as exc:  # noqa: BLE001  one component must not kill the page
        log.append((key, round((time.perf_counter() - t0) * 1000), -1))
        st.error(f"{key}: {exc}")
        return pd.DataFrame()


# ---------------------------------------------------------------- sidebar ----
st.session_state.setdefault("night", False)
if st.sidebar.button("Night mode" if not st.session_state.night else "Day mode"):
    st.session_state.night = not st.session_state.night
theme = DARK if st.session_state.night else LIGHT
st.markdown(page_css(theme), unsafe_allow_html=True)

try:
    min_date, max_date = data.date_bounds()
except Exception as exc:  # noqa: BLE001  no server / no DB → one clear stop
    st.error(f"Cannot reach the anfra server or data is missing: {exc}")
    st.stop()

preset = st.sidebar.radio("Window", PRESETS, index=1)  # default: Last 90 days
if preset != st.session_state.get("prev_preset"):
    st.session_state.prev_preset = preset
    if preset == "Last 30 days":
        st.session_state.date_range = (max_date - dt.timedelta(days=29), max_date)
    elif preset == "Year to date":
        st.session_state.date_range = (dt.date(max_date.year, 1, 1), max_date)
    elif preset == "All time":
        st.session_state.date_range = (min_date, max_date)
    else:
        st.session_state.date_range = (
            max_date - dt.timedelta(days=DEFAULT_WINDOW_DAYS - 1),
            max_date,
        )

date_range = st.sidebar.date_input(
    "Dates",
    value=st.session_state.get(
        "date_range", (max_date - dt.timedelta(days=DEFAULT_WINDOW_DAYS - 1), max_date)
    ),
    min_value=min_date,
    max_value=max_date,
    key="date_range",
)
if not isinstance(date_range, tuple) or len(date_range) != 2:
    date_range = st.session_state.get("date_range", (min_date, max_date))

picked_surfaces = tuple(st.sidebar.multiselect("Surfaces (empty = all)", data.SURFACES, default=[]))

st.session_state.setdefault("focus_surface", None)
frm, to = str(date_range[0]), str(date_range[1])

# ------------------------------------------------------------------ body -----
st.title("Run Volume")
st.caption(f"Weekly running volume and surface mix · window {frm} → {to}")

kpi = _run_query("kpi_totals", data.kpi_totals, frm, to, picked_surfaces)
c1, c2 = st.columns(2)
with c1:
    if kpi.empty:
        st.info("No runs in the selected window.")
    else:
        st.metric("Distance", f"{float(kpi['km'].iloc[0] or 0):.1f} km")
with c2:
    if kpi.empty:
        st.info("No runs in the selected window.")
    else:
        st.metric("Runs", f"{int(kpi['runs'].iloc[0] or 0)}")

st.header("Weekly volume")
st.caption("Weekly distance honors the surface filter and the donut focus; the donut is date-only.")

surfaces = picked_surfaces
if st.session_state.focus_surface:
    surfaces = (st.session_state.focus_surface,)
note = ", ".join(surfaces) if surfaces else "all surfaces"

left, right = st.columns(2)
with left:
    df = _run_query("weekly_distance", data.weekly_distance, frm, to, surfaces)
    if df.empty:
        st.info(f"No runs for **{note}** in the selected window.")
    else:
        st.plotly_chart(
            apply_layout(px.line(df, x="week_start", y="km"), theme, "Weekly km"),
            use_container_width=True,
            key="weekly_distance",
        )

with right:
    mix = _run_query("mix_by_surface", data.mix_by_surface, frm, to)
    if mix.empty:
        st.info("No runs in the selected window.")
    else:
        donut = px.pie(
            mix,
            names="run_surface",
            values="hours",
            hole=0.55,
            color="run_surface",
            color_discrete_map={s: surface_color(theme, s) for s in SURFACE_ORDER},
            custom_data=["run_surface"],
        )
        sel = st.plotly_chart(
            donut,
            use_container_width=True,
            key="mix_by_surface",
            on_select="rerun",
            selection_mode=("points",),
        )
        picked = None
        try:
            points = sel.selection.points  # type: ignore[union-attr]
            if points:
                raw = points[0].customdata
                picked = raw[0] if hasattr(raw, "__len__") else raw
                picked = str(picked)
        except Exception:  # noqa: BLE001, S110  no selection event in this context
            picked = st.session_state.focus_surface
        if picked != st.session_state.focus_surface:
            st.session_state.focus_surface = picked
            st.rerun()  # unconditional: also on clear — a stale banner is a bug

if st.session_state.focus_surface:
    st.info(
        f"Filtered to surface **{st.session_state.focus_surface}** "
        "(click the slice again, use the sidebar, or Clear)."
    )
    if st.button("Clear focus"):
        st.session_state.focus_surface = None
        st.rerun()

# ---------------------------------------------------------------- footer -----
with st.expander("Data load log", expanded=False):
    if st.session_state.load_log:
        st.dataframe(
            pd.DataFrame(st.session_state.load_log, columns=["component", "ms", "rows"]),
            use_container_width=True,
        )
st.caption(f"Data through {max_date} · anfra semantic layer via anfra_client")
