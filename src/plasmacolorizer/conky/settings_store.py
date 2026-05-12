"""JSON settings for Conky fetchers (ESV key, weather location)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ConkySettings:
    esv_api_key: str = ""
    weather_city: str = ""
    weather_lat: float | None = None
    weather_lon: float | None = None

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
        )


def _opt_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def config_dir() -> Path:
    return Path(os.path.expanduser("~/.config/plasmacolorizer"))


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
