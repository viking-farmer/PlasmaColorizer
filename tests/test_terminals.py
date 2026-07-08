"""Terminal backend color resolution, renderers, and apply dispatch."""

from __future__ import annotations

import pytest

from plasmacolorizer.core import terminals
from plasmacolorizer.core.palette import MaterialPalette
from plasmacolorizer.core.terminal_settings import TerminalSettings


def _palette() -> MaterialPalette:
    c = {
        "primary": (100, 150, 205),
        "secondary": (95, 155, 105),
        "tertiary": (195, 165, 85),
        "error": (220, 85, 95),
        "onBackground": (220, 220, 230),
        "onSurface": (230, 228, 238),
        "onSurfaceVariant": (150, 150, 160),
        "background": (18, 18, 22),
        "surface": (22, 22, 28),
        "outline": (125, 125, 135),
    }
    return MaterialPalette(is_dark=True, colors=c)


def test_resolve_uses_palette_when_no_overrides() -> None:
    colors = terminals.resolve_terminal_colors(_palette(), TerminalSettings())
    assert colors.background == (18, 18, 22)
    assert colors.cursor == (100, 150, 205)  # primary
    assert len(colors.normal) == 8
    assert len(colors.bright) == 8
    assert colors.opacity == 1.0


def test_resolve_applies_overrides() -> None:
    s = TerminalSettings(
        background_override="#000010",
        foreground_override="#ffffff",
        accent_override="#00ff00",
        opacity=0.5,
    )
    colors = terminals.resolve_terminal_colors(_palette(), s)
    assert colors.background == (0, 0, 16)
    assert colors.foreground == (255, 255, 255)
    assert colors.cursor == (0, 255, 0)
    assert colors.opacity == 0.5


def test_render_kitty_theme_has_all_colors() -> None:
    colors = terminals.resolve_terminal_colors(
        _palette(), TerminalSettings(font_family="Hack", font_size=12, opacity=0.9)
    )
    text = terminals.render_kitty_theme(colors)
    assert "background " in text
    assert "background_opacity 0.9" in text
    assert "font_family Hack" in text
    for i in range(16):
        assert f"color{i} #" in text


def test_render_alacritty_theme_is_toml_like() -> None:
    colors = terminals.resolve_terminal_colors(_palette(), TerminalSettings())
    text = terminals.render_alacritty_theme(colors)
    assert "[colors.primary]" in text
    assert "[colors.normal]" in text
    assert "[colors.bright]" in text
    assert 'background = "0x' in text
    assert "opacity = 1" in text


def test_render_xterm_resources() -> None:
    colors = terminals.resolve_terminal_colors(
        _palette(), TerminalSettings(font_family="Hack", font_size=10)
    )
    text = terminals.render_xterm_resources(colors)
    assert "*background:" in text
    assert "*color15:" in text
    assert "XTerm*faceName: Hack" in text


def test_kitty_apply_writes_files_and_include(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # Avoid touching the real system / pkill during the test.
    monkeypatch.setattr(terminals, "_reload_kitty", lambda: False)
    ok, msg = terminals.apply_terminal_theme(
        _palette(), TerminalSettings(terminal_id="kitty")
    )
    assert ok
    theme = terminals.kitty_config_dir() / "plasmacolorizer.conf"
    main = terminals.kitty_config_dir() / "kitty.conf"
    assert theme.is_file()
    assert "include plasmacolorizer.conf" in main.read_text(encoding="utf-8")
    # Idempotent: applying again does not duplicate the include line.
    terminals.apply_terminal_theme(_palette(), TerminalSettings(terminal_id="kitty"))
    assert main.read_text(encoding="utf-8").count("include plasmacolorizer.conf") == 1


def test_alacritty_apply_writes_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    ok, _msg = terminals.apply_terminal_theme(
        _palette(), TerminalSettings(terminal_id="alacritty")
    )
    assert ok
    theme = terminals.alacritty_config_dir() / "plasmacolorizer.toml"
    main = terminals.alacritty_config_dir() / "alacritty.toml"
    assert theme.is_file()
    assert "import" in main.read_text(encoding="utf-8")


def test_konsole_apply_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # No open Konsole in test env; apply still writes scheme + profile and returns.
    ok, msg = terminals.apply_terminal_theme(
        _palette(), TerminalSettings(terminal_id="konsole", opacity=0.8)
    )
    assert "konsole:" in msg
    scheme = tmp_path / ".local/share/konsole/PlasmaColorizer.colorscheme"
    assert scheme.is_file()
    assert "Opacity=0.8" in scheme.read_text(encoding="utf-8")


def test_installed_terminals_includes_konsole_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        terminals.shutil, "which", lambda name: "/usr/bin/x" if name == "konsole" else None
    )
    assert terminals.installed_terminals() == ["konsole"]


def test_unknown_terminal_falls_back_to_konsole(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    s = TerminalSettings()
    s.terminal_id = "bogus"  # dataclass field is mutable; bypasses validation
    ok, msg = terminals.apply_terminal_theme(_palette(), s)
    assert "konsole:" in msg
