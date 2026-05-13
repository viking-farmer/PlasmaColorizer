"""JSON settings for Conky fetchers (ESV key, weather location)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_SYSTEM_STATS_STYLES = frozenset({"text", "bar", "graph"})


@dataclass
class ConkySettings:
    esv_api_key: str = ""
    weather_city: str = ""
    weather_lat: float | None = None
    weather_lon: float | None = None
    weather_fahrenheit: bool = False
    # text | bar | graph — CPU/RAM lines in bundled "system" preset
    system_stats_style: str = "text"
    # 0–1 blends surface colour toward a neutral backdrop (opaque Conky panel; not ARGB alpha).
    conky_panel_opacity: float = 0.75
    # preset_id → Conky ``alignment`` (3×3 grid). Missing keys use bundled defaults.
    conky_preset_positions: dict[str, str] = field(default_factory=dict)
    # Install ~/.config/autostart/plasmacolorizer-conky.desktop and respawn last-running presets at login.
    autostart_enabled: bool = True
    # Preset ids that were running last time (updated whenever you Start/Stop a bundled preset).
    autostart_preset_ids: list[str] = field(default_factory=list)
    # Visual theme id (see ``plasmacolorizer.conky.themes.THEMES``); colors stay palette-driven.
    conky_theme_id: str = "material"

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_json_dict(cls, data: dict[str, Any] | None) -> ConkySettings:
        if not data:
            return cls()
        return cls(
            esv_api_key=str(data.get("esv_api_key") or ""),
            weather_city=str(data.get("weather_city") or ""),
            weather_lat=_opt_float(data.get("weather_lat")),
            weather_lon=_opt_float(data.get("weather_lon")),
            weather_fahrenheit=_opt_bool(data.get("weather_fahrenheit")),
            system_stats_style=_opt_system_stats_style(data.get("system_stats_style")),
            conky_panel_opacity=_opt_opacity(data.get("conky_panel_opacity")),
            conky_preset_positions=_opt_preset_positions(data.get("conky_preset_positions")),
            autostart_enabled=_opt_bool_with_default(data.get("autostart_enabled"), default=True),
            autostart_preset_ids=_opt_str_list(data.get("autostart_preset_ids")),
            conky_theme_id=_opt_theme_id(data.get("conky_theme_id")),
        )


def _opt_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return False


def _opt_system_stats_style(v: Any) -> str:
    s = str(v or "text").strip().lower()
    return s if s in _SYSTEM_STATS_STYLES else "text"


def _opt_opacity(v: Any) -> float:
    if v is None or v == "":
        return 0.75
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.75
    return max(0.0, min(1.0, x))


def _opt_preset_positions(v: Any) -> dict[str, str]:
    if not isinstance(v, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in v.items():
        if isinstance(key, str) and isinstance(val, str):
            out[key] = val
    return out


def _opt_bool_with_default(v: Any, *, default: bool) -> bool:
    if v is None:
        return default
    return _opt_bool(v)


def _opt_str_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    return [x for x in v if isinstance(x, str)]


def _opt_theme_id(v: Any) -> str:
    # Import lazily so this module stays free of theme dependencies during basic loads.
    from plasmacolorizer.conky.themes import DEFAULT_THEME_ID, THEMES

    s = (str(v) if v is not None else "").strip()
    return s if s in THEMES else DEFAULT_THEME_ID


def config_dir() -> Path:
    # Path.home() uses passwd when HOME is unset — Conky `execi` often has a minimal env.
    return Path.home() / ".config/plasmacolorizer"


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load_conky_settings() -> ConkySettings:
    path = settings_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ConkySettings()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ConkySettings()
    if not isinstance(data, dict):
        return ConkySettings()
    return ConkySettings.from_json_dict(data)


def save_conky_settings(settings: ConkySettings) -> Path:
    path = settings_path()
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
