"""Scheme role remapping for Plasma color application."""

from __future__ import annotations

from plasmacolorizer.core.plasma_scheme import (
    SchemeApplyChoices,
    normalize_scheme_apply_choices,
    remap_material_token,
)


def test_remap_default_is_identity() -> None:
    ch = SchemeApplyChoices()
    assert remap_material_token("surface", ch) == "surface"
    assert remap_material_token("primary", ch) == "primary"


def test_remap_accent_to_tertiary() -> None:
    ch = SchemeApplyChoices(accent="tertiary", emphasis="secondary", links=None)
    assert remap_material_token("primary", ch) == "tertiary"
    assert remap_material_token("primaryDim", ch) == "tertiaryDim"
    assert remap_material_token("onPrimary", ch) == "onTertiary"
    assert remap_material_token("inversePrimary", ch) == "inverseSurface"


def test_remap_emphasis_to_primary() -> None:
    ch = SchemeApplyChoices(accent="primary", emphasis="primary", links=None)
    assert remap_material_token("secondary", ch) == "primary"
    assert remap_material_token("secondaryDim", ch) == "primaryDim"


def test_normalize_invalid_accent() -> None:
    raw = SchemeApplyChoices(accent="not_a_color", emphasis="bogus", links="nope")
    n = normalize_scheme_apply_choices(raw)
    assert n.accent == "primary"
    assert n.emphasis == "secondary"
    assert n.links is None


def test_normalize_links() -> None:
    n = normalize_scheme_apply_choices(SchemeApplyChoices(links="tertiary"))
    assert n.links == "tertiary"
