"""TerminalSettings persistence and hex parsing."""

from __future__ import annotations

import pytest

from plasmacolorizer.core.terminal_settings import (
    DEFAULT_TERMINAL_ID,
    TerminalSettings,
    load_terminal_settings,
    parse_hex_rgb,
    save_terminal_settings,
)


def test_defaults_are_konsole() -> None:
    s = TerminalSettings()
    assert s.terminal_id == DEFAULT_TERMINAL_ID == "konsole"
    assert s.opacity == 1.0
    assert s.bold_intense is True
    assert s.font_family == ""


@pytest.mark.parametrize(
    "value,expected",
    [
        ("#ff8800", (255, 136, 0)),
        ("ff8800", (255, 136, 0)),
        ("#f80", (255, 136, 0)),
        ("  #FFFFFF ", (255, 255, 255)),
        ("nope", None),
        ("", None),
        ("#12345", None),
    ],
)
def test_parse_hex_rgb(value: str, expected) -> None:
    assert parse_hex_rgb(value) == expected


def test_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    s = TerminalSettings(
        terminal_id="kitty",
        font_family="Fira Code",
        font_size=13.5,
        bold_intense=False,
        background_override="#101018",
        foreground_override="#eeeeee",
        accent_override="#00ffcc",
        opacity=0.85,
    )
    save_terminal_settings(s)
    loaded = load_terminal_settings()
    assert loaded == s


def test_invalid_values_clamped_and_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    loaded = TerminalSettings.from_json_dict(
        {
            "terminal_id": "does-not-exist",
            "font_size": 999,
            "opacity": 5.0,
            "background_override": "garbage",
        }
    )
    assert loaded.terminal_id == "konsole"
    assert loaded.font_size == 72.0
    assert loaded.opacity == 1.0
    assert loaded.background_override == ""


def test_missing_file_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert load_terminal_settings() == TerminalSettings()
