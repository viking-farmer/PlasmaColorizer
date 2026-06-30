"""Component color override application."""

from __future__ import annotations

from plasmacolorizer.core.component_colors import (
    ComponentColorOverride,
    apply_component_color_overrides,
)
from plasmacolorizer.core.palette import MaterialPalette
from plasmacolorizer.core.plasma_scheme import SchemeApplyChoices, build_color_sections


def _palette() -> MaterialPalette:
    c = {
        "primary": (100, 120, 140),
        "primaryContainer": (40, 50, 60),
        "surfaceContainer": (20, 22, 24),
        "surfaceContainerHigh": (30, 32, 34),
        "secondary": (80, 90, 100),
        "tertiary": (90, 100, 110),
        "onSurface": (200, 200, 210),
        "outline": (100, 100, 110),
        "error": (200, 50, 50),
        "primaryDim": (70, 80, 90),
        "onPrimary": (10, 10, 20),
        "inversePrimary": (180, 180, 190),
        "inverseOnSurface": (30, 30, 40),
        "onSurfaceVariant": (150, 150, 160),
        "primaryFixed": (110, 130, 150),
        "primaryFixedDim": (90, 110, 130),
        "onPrimaryFixed": (10, 10, 20),
        "onSecondaryContainer": (20, 20, 30),
        "onErrorContainer": (30, 10, 10),
        "surface": (15, 15, 20),
        "surfaceContainerLow": (18, 18, 22),
        "surfaceContainerHighest": (35, 35, 40),
    }
    return MaterialPalette(is_dark=True, colors=c)


def test_custom_override_sets_panel_background() -> None:
    pal = _palette()
    sections = build_color_sections(pal)
    out = apply_component_color_overrides(
        sections,
        {"panel_background": ComponentColorOverride(source="custom", rgb=(11, 22, 33))},
        palette=pal,
    )
    assert out["Colors:Window"]["BackgroundNormal"] == "11,22,33"


def test_palette_override_resolves_token() -> None:
    pal = _palette()
    sections = build_color_sections(pal)
    out = apply_component_color_overrides(
        sections,
        {"panel_background": ComponentColorOverride(source="palette", palette_token="primary")},
        palette=pal,
    )
    assert out["Colors:Window"]["BackgroundNormal"] == "100,120,140"


def test_unknown_component_ignored() -> None:
    pal = _palette()
    sections = build_color_sections(pal)
    out = apply_component_color_overrides(
        sections,
        {"not_a_component": ComponentColorOverride(source="custom", rgb=(1, 2, 3))},
        palette=pal,
    )
    assert out == sections


def test_override_wins_over_strong_panel_tint() -> None:
    pal = _palette()
    ch = SchemeApplyChoices(strong_panel_tint=True)
    sections = build_color_sections(pal, ch)
    assert sections["Colors:Window"]["BackgroundNormal"] == "40,50,60"
    out = apply_component_color_overrides(
        sections,
        {"panel_background": ComponentColorOverride(source="custom", rgb=(99, 88, 77))},
        palette=pal,
    )
    assert out["Colors:Window"]["BackgroundNormal"] == "99,88,77"


def test_override_json_round_trip() -> None:
    o = ComponentColorOverride(source="palette", palette_token="tertiary")
    restored = ComponentColorOverride.from_json_dict(o.to_json_dict())
    assert restored is not None
    assert restored.source == "palette"
    assert restored.palette_token == "tertiary"

    c = ComponentColorOverride(source="custom", rgb=(1, 2, 3))
    restored_c = ComponentColorOverride.from_json_dict(c.to_json_dict())
    assert restored_c is not None
    assert restored_c.rgb == (1, 2, 3)
