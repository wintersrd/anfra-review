"""Theme invariants: the anfra app and streamlit theme must stay in sync."""

from __future__ import annotations

import re

import pytest
import theme

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

REQUIRED_KEYS = {
    "page",
    "card",
    "ink",
    "muted",
    "border",
    "grid",
    "pos",
    "neg",
    "categorical",
    "surface",
    "heatmap",
}


@pytest.mark.unit
class TestTheme:
    def test_both_modes_have_all_keys(self):
        for mode in (theme.LIGHT, theme.DARK):
            missing = REQUIRED_KEYS - set(mode)
            assert not missing, f"{mode} missing {missing}"

    def test_modes_differ(self):
        assert theme.LIGHT["page"] != theme.DARK["page"]

    def test_categorical_palette_is_full_hue(self):
        # "use the full palette" — 8 distinct hues, hex-valid, in both modes
        for mode in (theme.LIGHT, theme.DARK):
            cats = mode["categorical"]
            assert len(cats) == 8
            assert len(set(cats)) == 8
            assert all(HEX.match(c) for c in cats)

    def test_surface_colors_cover_all_surfaces(self):
        for mode in (theme.LIGHT, theme.DARK):
            assert set(mode["surface"]) == {"road", "trail", "indoor"}

    def test_heatmap_ramp_is_gradient(self):
        for mode in (theme.LIGHT, theme.DARK):
            ramp = mode["heatmap"]
            assert isinstance(ramp, list) and len(ramp) >= 3
            assert len(set(ramp)) == len(ramp)
            assert ramp[0] != ramp[-1]

    def test_helpers_use_theme(self):
        assert theme.surface_color(theme.LIGHT, "road") == theme.LIGHT["surface"]["road"]
        assert theme.palette(theme.DARK) == theme.DARK["categorical"]
