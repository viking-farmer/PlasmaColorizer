"""Palette override merge for manual swatches."""

from __future__ import annotations

from plasmacolorizer.core.palette import MaterialPalette, merge_palette_color_overrides


def _fake_palette() -> MaterialPalette:
    return MaterialPalette(
        is_dark=True,
        colors={
            "primary": (1, 2, 3),
            "secondary": (4, 5, 6),
            "surface": (7, 8, 9),
        },
    )


def test_merge_empty_returns_same_instance() -> None:
    pal = _fake_palette()
    assert merge_palette_color_overrides(pal, None) is pal
    assert merge_palette_color_overrides(pal, {}) is pal


def test_merge_replaces_known_keys() -> None:
    pal = _fake_palette()
    out = merge_palette_color_overrides(pal, {"primary": (10, 20, 30), "unknown": (99, 99, 99)})
    assert out is not pal
    assert out.colors["primary"] == (10, 20, 30)
    assert out.colors["secondary"] == (4, 5, 6)
    assert "unknown" not in out.colors
