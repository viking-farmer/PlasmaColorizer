"""Plasma shell apply path: desktop theme, plasmashellrc, live reload."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plasmacolorizer.core.app_settings import AppSettings, save_app_settings
from plasmacolorizer.core.palette import MaterialPalette
from plasmacolorizer.core import plasma_scheme
from plasmacolorizer.core.plasma_scheme import (
    DESKTOP_THEME_ID,
    PanelOpacityMode,
    SchemeApplyChoices,
    apply_plasma_panel_opacity_mode,
    merge_user_plasmarc_select_desktop_theme,
    notify_kde_palette_change,
    read_plasma_panel_opacity_mode,
    resolve_fallback_desktop_theme,
    write_plasma_desktop_theme,
)


def _minimal_palette() -> MaterialPalette:
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


def test_write_plasma_desktop_theme_adaptive_transparency_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    pal = _minimal_palette()
    root = write_plasma_desktop_theme(
        pal, adaptive_transparency_enabled=False, fallback_theme_id="default",
    )
    plasmarc = (root / "plasmarc").read_text(encoding="utf-8")
    assert "[AdaptiveTransparency]" in plasmarc
    assert "enabled=false" in plasmarc
    assert "FallbackTheme=default" in plasmarc
    assert "[ContrastEffect]" in plasmarc
    assert "enabled=false" in plasmarc.split("[ContrastEffect]")[1].split("[")[0]


def test_write_plasma_desktop_theme_adaptive_transparency_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    pal = _minimal_palette()
    root = write_plasma_desktop_theme(pal, adaptive_transparency_enabled=True)
    plasmarc = (root / "plasmarc").read_text(encoding="utf-8")
    assert "enabled=true" in plasmarc.split("[AdaptiveTransparency]")[1]


def test_merge_plasmarc_preserves_wallpapers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "plasmarc").write_text(
        "[Theme]\nname=breath-dark\n\n[Wallpapers]\nusersWallpapers=/tmp/a.jpg\n",
        encoding="utf-8",
    )
    merge_user_plasmarc_select_desktop_theme(DESKTOP_THEME_ID)
    text = (cfg / "plasmarc").read_text(encoding="utf-8")
    assert "name=PlasmaColorizer" in text
    assert "usersWallpapers=/tmp/a.jpg" in text


def test_resolve_fallback_uses_stored_app_setting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_app_settings(AppSettings(plasma_fallback_theme_id="my-old-theme"))
    monkeypatch.setattr(
        plasma_scheme, "_desktop_theme_exists", lambda tid: tid == "my-old-theme",
    )
    assert resolve_fallback_desktop_theme() == "my-old-theme"


def test_panel_opacity_mode_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "plasmashellrc").write_text(
        "[PlasmaViews][Panel 1]\nalignment=1\n\n[PlasmaViews][Panel 2]\n"
        "floating=1\npanelOpacity=0\n",
        encoding="utf-8",
    )
    assert read_plasma_panel_opacity_mode() == PanelOpacityMode.ADAPTIVE
    apply_plasma_panel_opacity_mode(PanelOpacityMode.OPAQUE)
    assert read_plasma_panel_opacity_mode() == PanelOpacityMode.OPAQUE
    apply_plasma_panel_opacity_mode(PanelOpacityMode.TRANSLUCENT)
    assert read_plasma_panel_opacity_mode() == PanelOpacityMode.TRANSLUCENT
    text = (cfg / "plasmashellrc").read_text(encoding="utf-8")
    assert text.count("panelOpacity=2") == 2


def test_panel_opacity_legacy_float_maps_to_adaptive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "plasmashellrc").write_text(
        "[PlasmaViews][Panel 2]\npanelOpacity=0.75\n",
        encoding="utf-8",
    )
    assert read_plasma_panel_opacity_mode() == PanelOpacityMode.ADAPTIVE


def test_strong_panel_tint_changes_window_background(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    pal = _minimal_palette()
    ch = SchemeApplyChoices(strong_panel_tint=True)
    from plasmacolorizer.core.plasma_scheme import build_color_sections

    sections = build_color_sections(pal, ch)
    assert sections["Colors:Window"]["BackgroundNormal"] == "40,50,60"


@patch("plasmacolorizer.core.plasma_scheme.subprocess.run")
def test_apply_plasma_desktop_theme_live_invokes_cli(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    ok, msg = plasma_scheme.apply_plasma_desktop_theme_live()
    assert ok is True
    assert "OK" in msg
    mock_run.assert_called_once()
    assert "plasma-apply-desktoptheme" in mock_run.call_args[0][0][0] or mock_run.call_args[0][0][0].endswith(
        "plasma-apply-desktoptheme",
    )


@patch("plasmacolorizer.core.plasma_scheme.apply_plasma_desktop_theme_live", return_value=(True, "live OK"))
@patch("plasmacolorizer.core.plasma_scheme.shutil.which", return_value="/usr/bin/kquitapp6")
def test_notify_kde_calls_desktop_theme_live_first(
    _which: MagicMock,
    mock_live: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pal = _minimal_palette()

    class _FakeBus:
        def get_object(self, *_a, **_k):
            raise OSError("no dbus in test")

    monkeypatch.setitem(
        __import__("sys").modules,
        "dbus",
        MagicMock(SessionBus=lambda: _FakeBus()),
    )
    ok, msg = notify_kde_palette_change(pal)
    mock_live.assert_called_once()
    assert "live OK" in msg
