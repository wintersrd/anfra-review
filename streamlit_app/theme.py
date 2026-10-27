"""Great Wave off Kanagawa theme: page CSS + Plotly layout templates."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

LIGHT: dict[str, Any] = {
    "page": "#F2EFE9",
    "page_alt": "#EFEAD8",
    "card": "#FAF7F0",
    "ink": "#16324F",
    "muted": "#5B6E80",
    "border": "rgba(22, 50, 79, 0.14)",
    "grid": "rgba(22, 50, 79, 0.08)",
    "pos": "#2C5F8A",
    "neg": "#B4533C",
    "categorical": [
        "#16324F",  # ink (primary)
        "#C9A66B",  # ochre
        "#4A6B57",  # pine
        "#3E7CB1",  # cerulean
        "#B4533C",  # vermilion
        "#7E6A8A",  # plum
        "#6FA8D0",  # pale indigo
        "#6E7F92",  # slate
    ],
    "surface": {"road": "#16324F", "trail": "#C9A66B", "indoor": "#6E7F92"},
    "ride": {"road": "#3E7CB1", "virtual": "#6E7F92", "mtb": "#C9A66B", "gravel": "#4A6B57"},
    "heatmap": ["#EFEAD8", "#C9A66B", "#3E7CB1", "#1E4368"],
}

DARK: dict[str, Any] = {
    "page": "#0E1B2A",
    "page_alt": "#12233A",
    "card": "#16283C",
    "ink": "#EAF0F6",
    "muted": "#93A9BF",
    "border": "rgba(234, 240, 246, 0.14)",
    "grid": "rgba(234, 240, 246, 0.08)",
    "pos": "#7FB3D8",
    "neg": "#D97B5F",
    "categorical": [
        "#A9CBE4",
        "#D9BC85",
        "#8FB39A",
        "#7FB3D8",
        "#D97B5F",
        "#B39DC4",
        "#4785B4",
        "#93A9BF",
    ],
    "surface": {"road": "#A9CBE4", "trail": "#D9BC85", "indoor": "#93A9BF"},
    "ride": {"road": "#7FB3D8", "virtual": "#93A9BF", "mtb": "#D9BC85", "gravel": "#8FB39A"},
    "heatmap": ["#16283C", "#1E4368", "#3E7CB1", "#A9CBE4"],
}

SURFACE_ORDER = ["road", "trail", "indoor"]

RIDE_ORDER = ["road", "virtual", "mtb", "gravel"]

RIDE_LABELS = {"road": "Road", "virtual": "Virtual", "mtb": "MTB", "gravel": "Gravel"}

SPORT_LABELS = {
    "run": "Run",
    "ride": "Ride",
    "walk": "Walk / Hike",
    "strength": "Strength",
    "yoga": "Yoga",
    "row": "Row",
    "other": "Other",
}


def palette(theme: dict[str, Any]) -> list[str]:
    return list(theme["categorical"])


def surface_color(theme: dict[str, Any], surface: str) -> str:
    return theme["surface"].get(surface, theme["muted"])


def ride_color(theme: dict[str, Any], ride_type: str) -> str:
    return theme["ride"].get(ride_type, theme["muted"])


def apply_layout(fig: go.Figure, theme: dict[str, Any], title: str, height: int = 300) -> go.Figure:
    """Apply the Great Wave look to a figure (transparent backgrounds)."""
    fig.update_layout(
        height=height,
        title=dict(text=title, font=dict(size=15, color=theme["ink"])),
        font=dict(family="Inter, -apple-system, sans-serif", color=theme["ink"], size=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=14, t=42, b=6),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.0,
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        ),
        hoverlabel=dict(
            bgcolor=theme["card"],
            bordercolor=theme["border"],
            font=dict(color=theme["ink"], family="Inter, sans-serif"),
        ),
        coloraxis=dict(colorscale=_heatmap_scale(theme)),
    )
    fig.update_xaxes(
        gridcolor=theme["grid"],
        zerolinecolor=theme["grid"],
        linecolor=theme["border"],
        tickfont=dict(size=11),
    )
    fig.update_yaxes(
        gridcolor=theme["grid"],
        zerolinecolor=theme["grid"],
        linecolor=theme["border"],
        tickfont=dict(size=11),
    )
    return fig


def _heatmap_scale(theme: dict[str, Any]) -> list[tuple[float, str]]:
    ramp = theme["heatmap"]
    if len(ramp) < 2:
        return [(0.0, ramp[0]), (1.0, ramp[-1])]
    step = 1.0 / (len(ramp) - 1)
    return [(i * step, color) for i, color in enumerate(ramp)]


def page_css(theme: dict[str, Any]) -> str:
    """Streamlit chrome restyled to match the Great Wave palette."""
    t = theme
    return f"""
    <style>
        .stApp {{
            background: linear-gradient(180deg, {t["page"]} 0%, {t["page_alt"]} 100%);
            color: {t["ink"]};
        }}
        [data-testid="stHeader"] {{ background: transparent; }}
        h1, h2, h3, h4, .stMarkdown p, label, [data-testid="stMetricLabel"] p {{
            color: {t["ink"]};
        }}
        [data-testid="stMetric"], .stPlotlyChart, [data-testid="stDataFrame"],
        [data-testid="stRadio"], [data-testid="stMultiSelect"], [data-testid="stDateInput"] {{
            background: {t["card"]};
            border: 1px solid {t["border"]};
            border-radius: 12px;
        }}
        [data-testid="stMetric"], .stPlotlyChart {{ padding: 10px 14px; }}
        [data-testid="stMetricValue"] {{ color: {t["ink"]}; }}
        [data-testid="stMetricDelta"] svg {{ vertical-align: middle; }}
        [data-testid="stSidebar"] {{
            background: {t["card"]};
            border-right: 1px solid {t["border"]};
        }}
        [data-testid="stSidebar"] * {{ color: {t["ink"]}; }}
        a {{ color: {t["pos"]}; }}
        .wave-caption {{ color: {t["muted"]}; font-size: 0.86rem; }}
        div[data-testid="stExpander"] {{
            border: 1px solid {t["border"]}; border-radius: 12px;
            background: {t["card"]};
        }}
        div[data-testid="stButton"] > button {{
            background: {t["card"]}; color: {t["ink"]};
            border: 1px solid {t["border"]}; border-radius: 999px;
        }}
    </style>
    """
