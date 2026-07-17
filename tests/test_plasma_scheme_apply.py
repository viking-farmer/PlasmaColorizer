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
    DiagnosticSeverity,
    PanelOpacityMode,
    SchemeApplyChoices,
    apply_plasma_panel_opacity_mode,
    collect_apply_diagnostics,
    merge_user_plasmarc_select_desktop_theme,
    notify_kde_palette_change,
    panel_opacity_diagnostics_need_repair,
    read_plasma_panel_opacity_mode,
    resolve_fallback_desktop_theme,
    run_panel_opacity_diagnostics,
    theme_plasmarc_has_breaking_sections,
    theme_plasmarc_needs_repair,
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
    # The generated theme must be minimal: only [Settings]/FallbackTheme. The
    # AdaptiveTransparency and ContrastEffect sections break per-panel opacity.
    monkeypatch.setenv("HOME", str(tmp_path))
    pal = _minimal_palette()
    root = write_plasma_desktop_theme(
        pal, adaptive_transparency_enabled=False, fallback_theme_id="default",
    )
    plasmarc = (root / "plasmarc").read_text(encoding="utf-8")
    assert "FallbackTheme=default" in plasmarc
    assert "[AdaptiveTransparency]" not in plasmarc
    assert "[ContrastEffect]" not in plasmarc


def test_write_plasma_desktop_theme_omits_opacity_breaking_sections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # AdaptiveTransparency / ContrastEffect sections (even disabled) override the
    # per-panel opacity mode, so the generated theme must not contain them.
    monkeypatch.setenv("HOME", str(tmp_path))
    pal = _minimal_palette()
    root = write_plasma_desktop_theme(pal, adaptive_transparency_enabled=True)
    plasmarc = (root / "plasmarc").read_text(encoding="utf-8")
    assert "[AdaptiveTransparency]" not in plasmarc
    assert "[ContrastEffect]" not in plasmarc
    assert "FallbackTheme=" in plasmarc


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


@patch("plasmacolorizer.core.plasma_scheme.apply_panel_opacity_via_script", return_value=(False, "no dbus"))
@patch("plasmacolorizer.core.plasma_scheme.restart_plasmashell", return_value=(True, "restarted"))
@patch("plasmacolorizer.core.plasma_scheme._patch_desktop_theme_adaptive_transparency", return_value=(True, "adaptive OK"))
def test_apply_plasma_panel_opacity_live_restarts_when_script_fails(
    _patch_adaptive: MagicMock,
    mock_restart: MagicMock,
    _script: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "plasmashellrc").write_text("[PlasmaViews][Panel 1]\n", encoding="utf-8")
    ok, msg = plasma_scheme.apply_plasma_panel_opacity_live(
        PanelOpacityMode.OPAQUE, allow_restart=True, allow_script=True,
    )
    assert ok is True
    assert "restarted" in msg
    mock_restart.assert_called_once()
    assert read_plasma_panel_opacity_mode() == PanelOpacityMode.OPAQUE


@patch("plasmacolorizer.core.plasma_scheme.apply_panel_opacity_via_script", return_value=(False, "no dbus"))
@patch("plasmacolorizer.core.plasma_scheme.restart_plasmashell", return_value=(True, "restarted"))
@patch("plasmacolorizer.core.plasma_scheme._patch_desktop_theme_adaptive_transparency", return_value=(True, "adaptive OK"))
def test_apply_plasma_panel_opacity_live_skips_restart_by_default(
    _patch_adaptive: MagicMock,
    mock_restart: MagicMock,
    _script: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Safe mode: never auto-restart plasmashell from the opacity combo."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "plasmashellrc").write_text("[PlasmaViews][Panel 1]\n", encoding="utf-8")
    ok, msg = plasma_scheme.apply_plasma_panel_opacity_live(PanelOpacityMode.OPAQUE)
    assert ok is True
    assert "safe mode" in msg
    mock_restart.assert_not_called()
    assert read_plasma_panel_opacity_mode() == PanelOpacityMode.OPAQUE


@patch("plasmacolorizer.core.plasma_scheme._panel_opacity_applied_via_script", return_value=True)
@patch("plasmacolorizer.core.plasma_scheme.apply_panel_opacity_via_script", return_value=(True, "scripting set opacity=opaque on 1 panel(s)"))
@patch("plasmacolorizer.core.plasma_scheme.restart_plasmashell", return_value=(True, "restarted"))
@patch("plasmacolorizer.core.plasma_scheme._patch_desktop_theme_adaptive_transparency", return_value=(True, "adaptive OK"))
def test_apply_plasma_panel_opacity_live_skips_restart_when_script_works(
    _patch_adaptive: MagicMock,
    mock_restart: MagicMock,
    _script: MagicMock,
    _verify: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "plasmashellrc").write_text("[PlasmaViews][Panel 1]\n", encoding="utf-8")
    ok, msg = plasma_scheme.apply_plasma_panel_opacity_live(
        PanelOpacityMode.OPAQUE, allow_script=True,
    )
    assert ok is True
    assert "no restart needed" in msg
    mock_restart.assert_not_called()


@patch("plasmacolorizer.core.plasma_scheme._panel_opacity_applied_via_script", return_value=False)
@patch("plasmacolorizer.core.plasma_scheme.apply_panel_opacity_via_script", return_value=(True, "set"))
@patch("plasmacolorizer.core.plasma_scheme.restart_plasmashell", return_value=(True, "restarted"))
@patch("plasmacolorizer.core.plasma_scheme._patch_desktop_theme_adaptive_transparency", return_value=(True, "adaptive off"))
def test_apply_plasma_panel_opacity_live_always_disables_adaptive_transparency(
    mock_patch: MagicMock,
    _restart: MagicMock,
    _script: MagicMock,
    _verify: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Regression: theme AdaptiveTransparency overrides per-panel opacity, so every
    # mode (including Translucent) must force it off.
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "plasmashellrc").write_text("[PlasmaViews][Panel 1]\n", encoding="utf-8")
    plasma_scheme.apply_plasma_panel_opacity_live(PanelOpacityMode.TRANSLUCENT)
    mock_patch.assert_called_once_with(enabled=False)


def test_detect_competing_panel_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    (cfg / "plasma-org.kde.plasma.desktop-appletsrc").parent.mkdir(parents=True, exist_ok=True)
    (cfg / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][2][Applets][27]\nplugin=luisbocanegra.kdematerialyou.colors\n",
        encoding="utf-8",
    )
    warnings = plasma_scheme.detect_competing_panel_tools()
    assert any("luisbocanegra" in w for w in warnings)


def test_detect_competing_panel_tools_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".config").mkdir(parents=True, exist_ok=True)
    assert plasma_scheme.detect_competing_panel_tools() == []


@patch("plasmacolorizer.core.plasma_scheme.apply_plasma_desktop_theme_live", return_value=(True, "reloaded"))
def test_strip_panel_opacity_breaking_sections_removes_them(
    _live: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    theme_dir = tmp_path / ".local/share/plasma/desktoptheme" / DESKTOP_THEME_ID
    theme_dir.mkdir(parents=True)
    (theme_dir / "plasmarc").write_text(
        "[Settings]\nFallbackTheme=default\n\n"
        "[ContrastEffect]\nenabled=false\n\n"
        "[AdaptiveTransparency]\nenabled=true\n",
        encoding="utf-8",
    )
    ok, _msg = plasma_scheme._strip_panel_opacity_breaking_sections()
    assert ok is True
    result = (theme_dir / "plasmarc").read_text(encoding="utf-8")
    assert "[AdaptiveTransparency]" not in result
    assert "[ContrastEffect]" not in result
    assert "FallbackTheme=default" in result


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
@patch("plasmacolorizer.core.plasma_scheme.apply_plasma_colorscheme_live", return_value=(True, "cs OK"))
@patch("plasmacolorizer.core.plasma_scheme.shutil.which", return_value="/usr/bin/kquitapp6")
def test_notify_kde_safe_mode_skips_desktop_theme_and_refresh(
    _which: MagicMock,
    mock_cs: MagicMock,
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
    monkeypatch.setattr(plasma_scheme, "plasmashell_dbus_ready", lambda: False)
    monkeypatch.setattr(plasma_scheme, "plasmashell_process_running", lambda: True)
    ok, msg = notify_kde_palette_change(pal)
    mock_cs.assert_called_once()
    mock_live.assert_not_called()
    assert ok is True
    assert "desktoptheme skipped" in msg
    assert "refreshCurrentShell skipped" in msg


@patch("plasmacolorizer.core.plasma_scheme.apply_plasma_desktop_theme_live", return_value=(True, "live OK"))
@patch("plasmacolorizer.core.plasma_scheme.apply_plasma_colorscheme_live", return_value=(True, "cs OK"))
def test_notify_kde_aggressive_calls_desktop_theme(
    mock_cs: MagicMock,
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
    monkeypatch.setattr(plasma_scheme, "plasmashell_dbus_ready", lambda: False)
    monkeypatch.setattr(plasma_scheme, "plasmashell_process_running", lambda: True)
    ok, msg = notify_kde_palette_change(pal, aggressive_shell_refresh=True)
    mock_cs.assert_called_once()
    mock_live.assert_called_once()
    assert ok is True
    assert "live OK" in msg


def test_theme_plasmarc_has_breaking_sections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    theme_dir = tmp_path / ".local/share/plasma/desktoptheme" / DESKTOP_THEME_ID
    theme_dir.mkdir(parents=True)
    (theme_dir / "plasmarc").write_text(
        "[Settings]\nFallbackTheme=default\n\n[AdaptiveTransparency]\nenabled=false\n",
        encoding="utf-8",
    )
    assert theme_plasmarc_has_breaking_sections() is True
    assert theme_plasmarc_needs_repair() is True


def test_theme_plasmarc_minimal_is_healthy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    theme_dir = tmp_path / ".local/share/plasma/desktoptheme" / DESKTOP_THEME_ID
    theme_dir.mkdir(parents=True)
    (theme_dir / "plasmarc").write_text("[Settings]\nFallbackTheme=default\n", encoding="utf-8")
    assert theme_plasmarc_has_breaking_sections() is False
    assert theme_plasmarc_needs_repair() is False


@patch("plasmacolorizer.core.plasma_scheme.run_plasma_shell_script", return_value=(True, "id=1 opacity=opaque"))
def test_run_panel_opacity_diagnostics_flags_breaking_plasmarc(
    _script: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "plasmashellrc").write_text(
        "[PlasmaViews][Panel 1]\npanelOpacity=2\n", encoding="utf-8",
    )
    (cfg / "plasmarc").write_text("[Theme]\nname=PlasmaColorizer\n", encoding="utf-8")
    theme_dir = tmp_path / ".local/share/plasma/desktoptheme" / DESKTOP_THEME_ID
    theme_dir.mkdir(parents=True)
    (theme_dir / "plasmarc").write_text(
        "[Settings]\nFallbackTheme=default\n\n[ContrastEffect]\nenabled=false\n",
        encoding="utf-8",
    )
    diags = run_panel_opacity_diagnostics()
    assert any(d.severity == DiagnosticSeverity.FAIL and d.category == "theme_plasmarc" for d in diags)
    assert panel_opacity_diagnostics_need_repair(diags) is True


@patch("plasmacolorizer.core.plasma_scheme.run_plasma_shell_script", return_value=(True, "id=1 opacity=opaque"))
def test_collect_apply_diagnostics_includes_panel_opacity_failures(
    _script: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    theme_dir = tmp_path / ".local/share/plasma/desktoptheme" / DESKTOP_THEME_ID
    theme_dir.mkdir(parents=True)
    (theme_dir / "plasmarc").write_text(
        "[Settings]\nFallbackTheme=default\n\n[AdaptiveTransparency]\nenabled=true\n",
        encoding="utf-8",
    )
    (tmp_path / ".config").mkdir(parents=True)
    (tmp_path / ".config" / "plasmarc").write_text("[Theme]\nname=PlasmaColorizer\n", encoding="utf-8")
    warnings = collect_apply_diagnostics()
    assert any("opacity-breaking" in w.lower() or "render identically" in w for w in warnings)


@patch("plasmacolorizer.core.plasma_scheme.restart_plasmashell", return_value=(True, "restarted"))
@patch("plasmacolorizer.core.plasma_scheme.apply_plasma_desktop_theme_live", return_value=(True, "reloaded"))
def test_repair_plasma_theme_for_panel_opacity(
    _live: MagicMock,
    mock_restart: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    theme_dir = tmp_path / ".local/share/plasma/desktoptheme" / DESKTOP_THEME_ID
    theme_dir.mkdir(parents=True)
    (theme_dir / "plasmarc").write_text(
        "[Settings]\nFallbackTheme=default\n\n[AdaptiveTransparency]\nenabled=true\n",
        encoding="utf-8",
    )
    ok, msg = plasma_scheme.repair_plasma_theme_for_panel_opacity()
    assert ok is True
    assert "safe mode" in msg
    mock_restart.assert_not_called()
    result = (theme_dir / "plasmarc").read_text(encoding="utf-8")
    assert "[AdaptiveTransparency]" not in result

    ok2, msg2 = plasma_scheme.repair_plasma_theme_for_panel_opacity(allow_restart=True)
    assert ok2 is True
    assert "restarted" in msg2
    mock_restart.assert_called_once()
