"""Bundled Conky presets: load templates, render with palette, start/stop processes."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from shutil import which

from plasmacolorizer.conky.templating import context_from_palette, render_template
from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex

# Whole-window alpha for ARGB Conky windows (~75% opaque / 25% transparent).
_CONKY_WINDOW_ALPHA = str(round(0.75 * 255))


@dataclass(frozen=True)
class PresetMeta:
    preset_id: str
    title: str
    template_name: str
    window_title: str


PRESETS: dict[str, PresetMeta] = {
    "system": PresetMeta(
        "system",
        "System (CPU, RAM, disk, network)",
        "system.conf.tpl",
        "PlasmaColorizer_system",
    ),
    "shortcuts": PresetMeta(
        "shortcuts",
        "Keyboard shortcuts (static)",
        "shortcuts.conf.tpl",
        "PlasmaColorizer_shortcuts",
    ),
    "verse": PresetMeta(
        "verse",
        "Bible verse (ESV API)",
        "verse.conf.tpl",
        "PlasmaColorizer_verse",
    ),
    "weather": PresetMeta(
        "weather",
        "Weather (Open-Meteo)",
        "weather.conf.tpl",
        "PlasmaColorizer_weather",
    ),
}


def rendered_dir() -> Path:
    return Path(os.path.expanduser("~/.local/share/plasmacolorizer/conky/rendered"))


def conky_cache_dir() -> Path:
    return Path(os.path.expanduser("~/.cache/plasmacolorizer/conky"))


def conky_binary() -> str | None:
    return which("conky")


def load_preset_template(preset_id: str) -> str:
    if preset_id not in PRESETS:
        raise KeyError(f"Unknown preset: {preset_id}")
    name = PRESETS[preset_id].template_name
    path = resources.files("plasmacolorizer.conky") / "templates" / name
    return path.read_text(encoding="utf-8")


def build_render_context(pal: MaterialPalette) -> dict[str, str]:
    ctx = dict(context_from_palette(pal))
    ctx["python_exec"] = shlex.quote(sys.executable)
    # Solid-ish panel behind text: avoids transparent-desktop compositor glitches when
    # other windows overlap; own_window_colour wants hex without leading '#'.
    surf = pal.colors.get("surface", (22, 22, 28))
    ctx["panel_bg_hex6"] = rgb_to_hex(surf).lstrip("#")
    ctx["conky_window_alpha"] = _CONKY_WINDOW_ALPHA
    return ctx


def render_preset(preset_id: str, pal: MaterialPalette) -> Path:
    """Write rendered ``~/.local/share/plasmacolorizer/conky/rendered/<id>.conf``."""
    if preset_id not in PRESETS:
        raise KeyError(f"Unknown preset: {preset_id}")
    raw = load_preset_template(preset_id)
    ctx = build_render_context(pal)
    body = render_template(raw, ctx)
    out_dir = rendered_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{preset_id}.conf"
    out.write_text(body, encoding="utf-8")
    return out


def _pid_file(preset_id: str) -> Path:
    conky_cache_dir().mkdir(parents=True, exist_ok=True)
    return conky_cache_dir() / f"{preset_id}.pid"


def is_preset_running(preset_id: str) -> bool:
    pf = _pid_file(preset_id)
    if not pf.is_file():
        return False
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
    except ValueError:
        pf.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        pf.unlink(missing_ok=True)
        return False
    return True


def stop_preset(preset_id: str) -> tuple[bool, str]:
    """SIGTERM the Conky instance we started for this preset."""
    pf = _pid_file(preset_id)
    if not pf.is_file():
        return True, "not running"
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
    except ValueError:
        pf.unlink(missing_ok=True)
        return True, "stale pid"
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pf.unlink(missing_ok=True)
        return True, "already exited"
    except PermissionError as exc:
        return False, str(exc)
    pf.unlink(missing_ok=True)
    return True, f"stopped pid {pid}"


def start_preset(preset_id: str, pal: MaterialPalette) -> tuple[bool, str]:
    """Render config and spawn ``conky -c …`` (no ``-d`` so PID stays valid)."""
    bin_path = conky_binary()
    if not bin_path:
        return False, "conky executable not found in PATH"

    cfg = render_preset(preset_id, pal)
    if is_preset_running(preset_id):
        stop_preset(preset_id)

    try:
        proc = subprocess.Popen(
            [bin_path, "-c", str(cfg)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return False, str(exc)

    _pid_file(preset_id).write_text(str(proc.pid), encoding="utf-8")
    return True, f"started pid {proc.pid} ({cfg})"


def stop_all_presets() -> None:
    for pid in PRESETS:
        if is_preset_running(pid):
            stop_preset(pid)


def render_all_presets(pal: MaterialPalette) -> dict[str, Path]:
    """Render every bundled preset (does not start Conky)."""
    return {pid: render_preset(pid, pal) for pid in PRESETS}
