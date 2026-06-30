"""App-wide settings (Plasma shell / panel) stored in ~/.config/plasmacolorizer/settings.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from plasmacolorizer.conky.settings_store import config_dir, settings_path


@dataclass
class AppSettings:
    # Plasma Style to inherit SVG assets from (captured before first PlasmaColorizer apply).
    plasma_fallback_theme_id: str = ""
    # KDE taskbar/panel opacity mode: opaque | adaptive | translucent (Plasma 6 integer enum).
    plasma_panel_opacity_mode: str = "opaque"
    # Tint panel backgrounds toward primaryContainer for stronger visible accent.
    plasma_strong_panel_tint: bool = False
    # Optional per-component KDE color overrides (component_id → override dict).
    plasma_component_colors: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: dict[str, Any] | None) -> AppSettings:
        if not data:
            return cls()
        mode = _resolve_panel_opacity_mode(data)
        raw_comp = data.get("plasma_component_colors")
        comp: dict[str, dict[str, Any]] = {}
        if isinstance(raw_comp, dict):
            for k, v in raw_comp.items():
                if isinstance(k, str) and isinstance(v, dict):
                    comp[k] = dict(v)
        return cls(
            plasma_fallback_theme_id=str(data.get("plasma_fallback_theme_id") or "").strip(),
            plasma_panel_opacity_mode=mode,
            plasma_strong_panel_tint=_opt_bool(
                data.get("plasma_strong_panel_tint"), default=False,
            ),
            plasma_component_colors=comp,
        )


def _resolve_panel_opacity_mode(data: dict[str, Any]) -> str:
    raw = data.get("plasma_panel_opacity_mode")
    if isinstance(raw, str) and raw.strip().lower() in ("opaque", "adaptive", "translucent"):
        return raw.strip().lower()
    # Migrate legacy float slider settings.
    enabled = _opt_bool(data.get("plasma_panel_transparency_enabled"), default=False)
    if not enabled:
        return "opaque"
    trans = _opt_float_range(data.get("plasma_panel_transparency"), default=0.0)
    if trans > 0.5:
        return "translucent"
    if trans > 0.0:
        return "adaptive"
    return "opaque"


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


def _opt_float_range(v: Any, *, default: float) -> float:
    if v is None or v == "":
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, x))


def _read_settings_json() -> dict[str, Any]:
    path = settings_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_app_settings() -> AppSettings:
    return AppSettings.from_json_dict(_read_settings_json())


def save_app_settings(settings: AppSettings) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _read_settings_json()
    merged.update(settings.to_json_dict())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
