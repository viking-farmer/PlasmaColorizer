"""Konsole colorscheme generation and profile patching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plasmacolorizer.core.konsole_scheme import (
    KONSOLE_SCHEME_ALT_ID,
    KONSOLE_SCHEME_ID,
    apply_konsole_scheme,
    konsole_cohesion_warnings,
    konsole_font_string,
    patch_konsole_profile_color_scheme,
    read_default_konsole_profile_name,
    render_konsole_colorscheme,
    write_konsole_colorscheme,
)
from plasmacolorizer.core.palette import MaterialPalette


def _minimal_palette() -> MaterialPalette:
    c = {
        "background": (19, 19, 24),
        "onBackground": (231, 228, 240),
        "primary": (100, 120, 140),
        "primaryFixed": (160, 195, 250),
        "surface": (15, 15, 20),
        "surfaceContainerLow": (18, 18, 22),
        "surfaceContainer": (20, 22, 24),
        "surfaceContainerHigh": (30, 32, 34),
        "surfaceContainerHighest": (35, 35, 40),
        "surfaceContainerLowest": (12, 12, 16),
        "onSurface": (200, 200, 210),
        "onSurfaceVariant": (150, 150, 160),
        "secondary": (80, 140, 95),
        "secondaryFixed": (90, 185, 185),
        "onSecondaryFixed": (115, 215, 215),
        "tertiary": (195, 165, 85),
        "tertiaryFixed": (225, 195, 115),
        "tertiaryContainer": (155, 95, 155),
        "onTertiaryFixed": (215, 155, 215),
        "outline": (100, 100, 110),
        "outlineVariant": (90, 90, 100),
        "error": (220, 85, 95),
        "errorContainer": (250, 145, 155),
        "onPrimary": (10, 10, 20),
        "onSecondary": (20, 20, 30),
        "onTertiary": (20, 20, 30),
        "onError": (30, 10, 10),
        "inversePrimary": (180, 180, 190),
        "inverseOnSurface": (30, 30, 40),
    }
    return MaterialPalette(is_dark=True, colors=c)


def test_render_konsole_colorscheme_has_sections() -> None:
    text = render_konsole_colorscheme(_minimal_palette())
    assert "[Background]" in text
    assert "[Foreground]" in text
    assert "[Color0]" in text
    assert "[Color7]" in text
    assert f"Description={KONSOLE_SCHEME_ID}" in text
    assert "Color=231,228,240" in text  # onBackground foreground text
    assert "Color=160,195,250" in text  # primaryFixed bold / Color4Intense


def test_write_konsole_colorscheme_writes_mirror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    write_konsole_colorscheme(_minimal_palette())
    primary = tmp_path / f".local/share/konsole/{KONSOLE_SCHEME_ID}.colorscheme"
    alt = tmp_path / f".local/share/konsole/{KONSOLE_SCHEME_ALT_ID}.colorscheme"
    assert primary.is_file()
    assert alt.is_file()
    assert f"Description={KONSOLE_SCHEME_ALT_ID}" in alt.read_text(encoding="utf-8")


def test_write_konsole_colorscheme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = write_konsole_colorscheme(_minimal_palette())
    assert path.name == f"{KONSOLE_SCHEME_ID}.colorscheme"
    assert path.is_file()
    assert "[Background]" in path.read_text(encoding="utf-8")


def test_read_default_konsole_profile_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "konsolerc").write_text("DefaultProfile=My Profile.profile\n", encoding="utf-8")
    assert read_default_konsole_profile_name() == "My Profile"


def test_patch_konsole_profile_color_scheme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    konsole = tmp_path / ".local/share/konsole"
    konsole.mkdir(parents=True)
    prof = konsole / "Profile 1.profile"
    prof.write_text(
        "[General]\nName=Profile 1\n[Appearance]\nColorScheme=MaterialYou\n",
        encoding="utf-8",
    )
    patch_konsole_profile_color_scheme("Profile 1")
    text = prof.read_text(encoding="utf-8")
    assert f"ColorScheme={KONSOLE_SCHEME_ID}" in text
    assert "BoldIntenseColors=true" in text
    assert "MaterialYou" not in text


def test_konsole_cohesion_warnings_stale_scheme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    konsole = tmp_path / ".local/share/konsole"
    konsole.mkdir(parents=True)
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "konsolerc").write_text("DefaultProfile=Profile 1.profile\n", encoding="utf-8")
    (konsole / "Profile 1.profile").write_text(
        "[Appearance]\nColorScheme=MaterialYouAlt\n",
        encoding="utf-8",
    )
    warnings = konsole_cohesion_warnings()
    assert len(warnings) == 1
    assert "MaterialYou" in warnings[0]


def test_render_konsole_colorscheme_opacity_and_overrides() -> None:
    text = render_konsole_colorscheme(
        _minimal_palette(),
        opacity=0.75,
        background_override=(1, 2, 3),
        foreground_override=(250, 251, 252),
    )
    assert "Opacity=0.75" in text
    assert "Blur=true" in text
    assert "Color=1,2,3" in text  # background override
    assert "Color=250,251,252" in text  # foreground override


def test_render_konsole_colorscheme_opaque_disables_blur() -> None:
    text = render_konsole_colorscheme(_minimal_palette(), opacity=1.0)
    assert "Opacity=1" in text
    assert "Blur=false" in text


def test_konsole_font_string_format() -> None:
    assert konsole_font_string("Fira Code", 12) == "Fira Code,12,-1,5,50,0,0,0,0,0"
    assert konsole_font_string("Hack", 10.5) == "Hack,10.5,-1,5,50,0,0,0,0,0"


def test_patch_konsole_profile_sets_font_and_bold_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    konsole = tmp_path / ".local/share/konsole"
    konsole.mkdir(parents=True)
    prof = konsole / "Profile 1.profile"
    prof.write_text(
        "[General]\nName=Profile 1\n[Appearance]\nColorScheme=Old\n",
        encoding="utf-8",
    )
    patch_konsole_profile_color_scheme(
        "Profile 1",
        bold_intense=False,
        font=konsole_font_string("Hack", 11),
    )
    text = prof.read_text(encoding="utf-8")
    assert "BoldIntenseColors=false" in text
    assert "Font=Hack,11,-1,5,50,0,0,0,0,0" in text


def test_apply_konsole_scheme_writes_and_patches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    with patch(
        "plasmacolorizer.core.konsole_scheme.reload_open_konsole_sessions",
        return_value=(True, "no open Konsole sessions"),
    ):
        ok, msg = apply_konsole_scheme(_minimal_palette())
    assert ok
    assert "PlasmaColorizer.colorscheme" in msg
    scheme = tmp_path / ".local/share/konsole/PlasmaColorizer.colorscheme"
    assert scheme.is_file()
    prof = tmp_path / ".local/share/konsole/Profile 1.profile"
    assert prof.is_file()
    assert f"ColorScheme={KONSOLE_SCHEME_ID}" in prof.read_text(encoding="utf-8")
