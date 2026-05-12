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
    assert "own_window_transparent = false" in body
    assert "own_window_colour =" in body
    assert "131318" in body  # blended panel at default 75% opacity (surface + backdrop)
    assert "own_window_argb_visual = false" in body
    assert "own_window_type = 'dock'" in body
    assert "own_window_argb_value" not in body
    assert "alignment = 'top_right'" in body


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


def test_render_system_preset_graph(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(system_stats_style="graph"))
    out = presets.render_preset("system", _minimal_palette())
    body = out.read_text(encoding="utf-8")
    assert "cpugraph" in body
    assert "memgraph" in body
    assert "minimum_width = 280" in body
