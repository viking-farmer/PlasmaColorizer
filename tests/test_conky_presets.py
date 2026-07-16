"""Bundled Conky preset rendering."""

from __future__ import annotations

import pytest

from plasmacolorizer.conky import presets
from plasmacolorizer.conky.settings_store import (
    ConkyShortcut,
    ConkySettings,
    default_conky_shortcuts,
    load_conky_settings,
    save_conky_settings,
)
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
    assert "0f0f14" in body  # pure surface color (transparency comes from ARGB alpha)
    assert "own_window_argb_visual = true" in body
    # Use ``normal`` + ``below`` by default so panels stay visible on Plasma Wayland
    # (``desktop``-type windows sit under plasmashell's wallpaper surface).
    assert "own_window_type = 'normal'" in body
    assert "below" in body
    assert "out_to_x = true" in body
    assert "out_to_wayland = false" in body
    # Default opacity 0.75 → alpha = 191. Slider position is (1 - opacity).
    assert "own_window_argb_value = 191" in body
    assert "own_window_class = 'PlasmaColorizerConky'" in body
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
    assert ctx["panel_bg_hex6"] == "0f0f14"  # pure surface
    assert ctx["conky_window_alpha"] == "255"


def test_build_render_context_full_transparency(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(conky_panel_opacity=0.0))
    ctx = presets.build_render_context(_minimal_palette())
    assert ctx["conky_window_alpha"] == "0"


def test_opacity_to_cardinal_endpoints_and_midpoint() -> None:
    # _NET_WM_WINDOW_OPACITY is a 32-bit CARDINAL: 0 = fully transparent,
    # 0xFFFFFFFF = fully opaque.
    assert presets._opacity_to_cardinal(0.0) == 0
    assert presets._opacity_to_cardinal(1.0) == 0xFFFFFFFF
    # 0.5 -> 0x7FFFFFFF or 0x80000000 (rounding); we accept either side of .5.
    mid = presets._opacity_to_cardinal(0.5)
    assert mid in (0x7FFFFFFF, 0x80000000)
    # Out-of-range inputs clamp instead of overflowing.
    assert presets._opacity_to_cardinal(-0.25) == 0
    assert presets._opacity_to_cardinal(1.7) == 0xFFFFFFFF


def test_apply_window_opacity_noop_without_xprop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No xprop installed → silent no-op, no thread spawned, no subprocess call."""
    monkeypatch.setattr(presets, "which", lambda _name: None)

    def _boom(*_a, **_kw):
        raise AssertionError("subprocess.run must not be called when xprop is missing")

    monkeypatch.setattr(presets.subprocess, "run", _boom)
    presets._apply_window_opacity("PlasmaColorizer_test", 0.5)


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


def test_shortcuts_default_body_renders_bundled_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    body = presets.render_preset("shortcuts", _minimal_palette()).read_text(encoding="utf-8")
    assert "{{shortcuts_body}}" not in body
    assert "${color1}Launcher${alignr}Meta" in body
    assert "${color1}Close window${alignr}Meta+Shift+W" in body


def test_shortcuts_body_uses_custom_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(
        ConkySettings(
            conky_shortcuts=[
                ConkyShortcut("Terminal", "Ctrl+Alt+T"),
                ConkyShortcut("Files", "Meta+E"),
            ]
        )
    )
    body = presets.render_preset("shortcuts", _minimal_palette()).read_text(encoding="utf-8")
    assert "${color1}Terminal${alignr}Ctrl+Alt+T" in body
    assert "${color1}Files${alignr}Meta+E" in body
    # Bundled defaults must not leak in once the user has customized.
    assert "Launcher" not in body


def test_shortcuts_body_empty_list_renders_no_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(conky_shortcuts=[]))
    body = presets.render_preset("shortcuts", _minimal_palette()).read_text(encoding="utf-8")
    assert "${alignr}" not in body
    assert "{{shortcuts_body}}" not in body


def test_shortcuts_body_label_only_omits_alignr() -> None:
    ctx = presets.build_render_context(
        _minimal_palette(),
    )
    # Direct helper check: a label with no keys renders without the ${alignr} split.
    line = presets._shortcuts_body(
        ConkySettings(conky_shortcuts=[ConkyShortcut("Heading", "")])
    )
    assert line == "${color1}Heading"
    assert isinstance(ctx, dict)


def test_shortcuts_body_escapes_dollar_signs() -> None:
    line = presets._shortcuts_body(
        ConkySettings(conky_shortcuts=[ConkyShortcut("Cost", "$5")])
    )
    # A literal '$' must become '$$' so Conky does not treat it as a variable.
    assert "$$5" in line
    assert "${color1}Cost${alignr}$$5" == line


def test_shortcuts_roundtrip_through_settings_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(
        ConkySettings(conky_shortcuts=[ConkyShortcut("Lock", "Meta+L")])
    )
    loaded = load_conky_settings()
    assert loaded.conky_shortcuts == [ConkyShortcut("Lock", "Meta+L")]


def test_shortcuts_missing_key_falls_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # Simulate an older settings.json without the conky_shortcuts key.
    path = tmp_path / ".config/plasmacolorizer/settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"conky_theme_id": "material"}', encoding="utf-8")
    loaded = load_conky_settings()
    assert loaded.conky_shortcuts == default_conky_shortcuts()
