"""Bundled Conky preset rendering."""

from __future__ import annotations

import pytest

from plasmacolorizer.conky import presets
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
    assert "0f0f14" in body  # surface (15,15,20) → panel_bg_hex6
    assert "own_window_argb_value = 191" in body


def test_build_render_context_has_python_exec() -> None:
    ctx = presets.build_render_context(_minimal_palette())
    assert "python_exec" in ctx
    assert len(ctx["python_exec"]) > 0
