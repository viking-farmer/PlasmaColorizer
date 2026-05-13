"""Bundled Conky preset rendering."""

from __future__ import annotations

import pytest

from plasmacolorizer.conky import presets
from plasmacolorizer.conky.settings_store import ConkySettings, save_conky_settings
from plasmacolorizer.core.palette import MaterialPalette


def _minimal_palette() -> MaterialPalette:
    c = {
        "primary": (10, 20, 30),
        "secondary": (40, 50, 60),
        "tertiary": (70, 80, 90),
        "onSurface": (200, 200, 210),
        "surface": (15, 15, 20),
    }
    return MaterialPalette(is_dark=True, colors=c)


def test_load_preset_template_shortcuts() -> None:
    text = presets.load_preset_template("shortcuts")
    assert "{{primary}}" in text
    assert "PlasmaColorizer_shortcuts" in text


def test_render_preset_substitutes_hex(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    pal = _minimal_palette()
    out = presets.render_preset("shortcuts", pal)
    assert out.is_file()
    body = out.read_text(encoding="utf-8")
    assert "#0a141e" in body  # primary
    assert "{{primary}}" not in body
    assert "{{python_exec}}" not in body
    assert "{{theme_font_body}}" not in body
    assert "{{theme_title_open}}" not in body
    assert "own_window_transparent = false" in body
    assert "own_window_colour =" in body
    assert "131318" in body  # blended panel at default 75% opacity (surface + backdrop)
    assert "own_window_argb_visual = false" in body
    # Conkys must stay below normal windows (desktop layer in KWin).
    assert "own_window_type = 'desktop'" in body
    assert "own_window_argb_value" not in body
    assert "alignment = 'top_right'" in body
    # default theme = Material Minimal: sans:size=10 body font and hr-1 divider.
    assert "font = 'sans:size=10'" in body
    assert "${hr 1}" in body


def test_render_preset_position_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(
        ConkySettings(conky_preset_positions={"system": "middle_middle", "weather": "top_middle"})
    )
    out_sys = presets.render_preset("system", _minimal_palette())
    assert "alignment = 'middle_middle'" in out_sys.read_text(encoding="utf-8")
    out_w = presets.render_preset("weather", _minimal_palette())
    assert "alignment = 'top_middle'" in out_w.read_text(encoding="utf-8")


def test_build_render_context_has_python_exec() -> None:
    ctx = presets.build_render_context(_minimal_palette())
    assert "python_exec" in ctx
    assert len(ctx["python_exec"]) > 0
    assert ctx.get("conky_alignment") == "top_left"


def test_build_render_context_alignment_for_preset(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert presets.build_render_context(_minimal_palette(), preset_id="weather")["conky_alignment"] == "bottom_right"
    save_conky_settings(ConkySettings(conky_preset_positions={"weather": "middle_left"}))
    assert (
        presets.build_render_context(_minimal_palette(), preset_id="weather")["conky_alignment"] == "middle_left"
    )


def test_build_render_context_system_stats_body_default_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    ctx = presets.build_render_context(_minimal_palette())
    assert "system_stats_body" in ctx
    assert "${cpu cpu0}%" in ctx["system_stats_body"]
    assert "cpubar" not in ctx["system_stats_body"]
    assert ctx["system_min_width"] == "220"


def test_render_system_preset_bar(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(system_stats_style="bar"))
    out = presets.render_preset("system", _minimal_palette())
    body = out.read_text(encoding="utf-8")
    assert "cpubar" in body
    assert "membar" in body
    assert "minimum_width = 280" in body


def test_build_render_context_panel_opacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(conky_panel_opacity=1.0))
    ctx = presets.build_render_context(_minimal_palette())
    assert ctx["panel_bg_hex6"] == "0f0f14"  # pure surface at 100%
    assert "conky_window_alpha" not in ctx


def test_blend_panel_opacity_mid_and_zero() -> None:
    assert presets._blend_panel_opacity((15, 15, 20), is_dark=True, opacity=0.75) == (19, 19, 24)
    assert presets._blend_panel_opacity((15, 15, 20), is_dark=True, opacity=0.0) == (30, 30, 36)


def test_theme_overrides_system_widget_style(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # User wants text, but the "bars" theme should force bars regardless.
    save_conky_settings(
        ConkySettings(conky_theme_id="bars", system_stats_style="text")
    )
    out = presets.render_preset("system", _minimal_palette()).read_text(encoding="utf-8")
    assert "cpubar" in out
    assert "minimum_width = 280" in out


def test_theme_changes_font_and_divider(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(conky_theme_id="gotham"))
    body = presets.render_preset("verse", _minimal_palette()).read_text(encoding="utf-8")
    assert "font = 'DejaVu Sans Mono:size=9'" in body
    assert "${stippled_hr 1 2}" in body


def test_theme_invalid_id_falls_back_to_default(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(conky_theme_id="does-not-exist"))
    body = presets.render_preset("system", _minimal_palette()).read_text(encoding="utf-8")
    assert "font = 'sans:size=10'" in body


def test_autostart_install_uninstall(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert presets.autostart_entry_installed() is False
    path = presets.install_autostart_entry()
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert "Type=Application" in body
    assert "plasmacolorizer.conky.autostart" in body
    assert presets.autostart_entry_installed() is True
    assert presets.uninstall_autostart_entry() is True
    assert presets.autostart_entry_installed() is False
    assert presets.uninstall_autostart_entry() is False


def test_start_preset_from_rendered_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    ok, msg = presets.start_preset_from_rendered("system")
    assert ok is False
    assert "no rendered config" in msg


def test_render_system_preset_graph(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(system_stats_style="graph"))
    out = presets.render_preset("system", _minimal_palette())
    body = out.read_text(encoding="utf-8")
    assert "cpugraph" in body
    assert "memgraph" in body
    assert "minimum_width = 280" in body
