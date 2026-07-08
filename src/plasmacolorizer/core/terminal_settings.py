"""Persistent settings for terminal theming (Konsole + optional other terminals).

Stored separately from the Plasma/Conky settings so a save here never risks
clobbering the shared ``settings.json`` file.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from plasmacolorizer.conky.settings_store import config_dir

# Terminal backend ids known to the app. ``konsole`` is the KDE default.
KNOWN_TERMINAL_IDS = ("konsole", "kitty", "alacritty", "xterm")
DEFAULT_TERMINAL_ID = "konsole"


@dataclass
class TerminalSettings:
    """User-facing terminal theming options.

    Colour overrides are ``"#rrggbb"`` strings; an empty string means "derive
    this colour from the wallpaper palette". ``font_family`` empty means "leave
    the terminal's own font untouched".
    """

    terminal_id: str = DEFAULT_TERMINAL_ID
    font_family: str = ""
    font_size: float = 11.0
    bold_intense: bool = True
    background_override: str = ""
    foreground_override: str = ""
    accent_override: str = ""
    opacity: float = 1.0

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: dict[str, Any] | None) -> "TerminalSettings":
        if not data:
            return cls()
        return cls(
            terminal_id=_opt_terminal_id(data.get("terminal_id")),
            font_family=_opt_str(data.get("font_family")),
            font_size=_opt_font_size(data.get("font_size")),
            bold_intense=_opt_bool(data.get("bold_intense"), default=True),
            background_override=_opt_hex(data.get("background_override")),
            foreground_override=_opt_hex(data.get("foreground_override")),
            accent_override=_opt_hex(data.get("accent_override")),
            opacity=_opt_opacity(data.get("opacity")),
        )


def _opt_terminal_id(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s if s in KNOWN_TERMINAL_IDS else DEFAULT_TERMINAL_ID


def _opt_str(v: Any) -> str:
    return str(v).strip() if isinstance(v, str) else ""


def _opt_bool(v: Any, *, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default


def _opt_font_size(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 11.0
    return max(5.0, min(72.0, x))


def _opt_opacity(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, x))


def parse_hex_rgb(value: str) -> tuple[int, int, int] | None:
    """Parse ``#rrggbb`` / ``rrggbb`` (also short ``#rgb``) into an RGB tuple."""
    s = (value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _opt_hex(v: Any) -> str:
    if not isinstance(v, str):
        return ""
    rgb = parse_hex_rgb(v)
    if rgb is None:
        return ""
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def terminal_settings_path() -> Path:
    return config_dir() / "terminal.json"


def load_terminal_settings() -> TerminalSettings:
    path = terminal_settings_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return TerminalSettings()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return TerminalSettings()
    if not isinstance(data, dict):
        return TerminalSettings()
    return TerminalSettings.from_json_dict(data)


def save_terminal_settings(settings: TerminalSettings) -> Path:
    path = terminal_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(settings.to_json_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
