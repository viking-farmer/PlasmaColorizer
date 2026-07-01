"""Konsole colorscheme generation and profile patching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plasmacolorizer.core.konsole_scheme import (
    KONSOLE_SCHEME_ID,
    apply_konsole_scheme,
    konsole_cohesion_warnings,
    patch_konsole_profile_color_scheme,
    read_default_konsole_profile_name,
    render_konsole_colorscheme,
    write_konsole_colorscheme,
)
from plasmacolorizer.core.palette import MaterialPalette


def _minimal_palette() -> MaterialPalette:
    c = {
        "primary": (100, 120, 140),
        "surface": (15, 15, 20),
        "surfaceContainerLow": (18, 18, 22),
        "surfaceContainer": (20, 22, 24),
        "surfaceContainerHigh": (30, 32, 34),
        "surfaceContainerHighest": (35, 35, 40),
        "onSurface": (200, 200, 210),
        "onSurfaceVariant": (150, 150, 160),
        "secondary": (80, 90, 100),
        "tertiary": (90, 100, 110),
        "outline": (100, 100, 110),
        "error": (200, 50, 50),
        "onPrimary": (10, 10, 20),
        "onSecondary": (20, 20, 30),
        "onTertiary": (20, 20, 30),
        "onError": (30, 10, 10),
        "primaryFixed": (110, 130, 150),
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
