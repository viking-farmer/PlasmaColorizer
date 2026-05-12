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

from plasmacolorizer.conky.settings_store import load_conky_settings
from plasmacolorizer.conky.templating import context_from_palette, render_template
from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex

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

# Conky ``alignment`` (3×3 grid). Labels are for the UI; values match Conky’s config.
CONKY_GRID_ALIGNMENTS: tuple[tuple[str, str], ...] = (
    ("top_left", "Top left"),
    ("top_middle", "Top center"),
    ("top_right", "Top right"),
    ("middle_left", "Middle left"),
    ("middle_middle", "Center"),
    ("middle_right", "Middle right"),
    ("bottom_left", "Bottom left"),
    ("bottom_middle", "Bottom center"),
    ("bottom_right", "Bottom right"),
)

_CONKY_ALIGNMENT_IDS: frozenset[str] = frozenset(a for a, _ in CONKY_GRID_ALIGNMENTS)

_DEFAULT_ALIGNMENT_FOR_PRESET: dict[str, str] = {
    "system": "top_left",
    "shortcuts": "top_right",
    "verse": "bottom_left",
    "weather": "bottom_right",
}


def default_alignment_for_preset(preset_id: str) -> str:
    """Original corner defaults for each bundled preset (before user overrides)."""
    return _DEFAULT_ALIGNMENT_FOR_PRESET.get(preset_id, "top_left")


def alignment_for_preset(preset_id: str) -> str:
    """Effective alignment: saved setting if valid, else bundled default."""
    if preset_id not in PRESETS:
        return "top_left"
    stored = (load_conky_settings().conky_preset_positions.get(preset_id) or "").strip()
    if stored in _CONKY_ALIGNMENT_IDS:
        return stored
    return default_alignment_for_preset(preset_id)


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


def _hex6(pal: MaterialPalette, key: str, default: tuple[int, int, int]) -> str:
    return rgb_to_hex(pal.colors.get(key, default)).lstrip("#")


# Neutral “desktop behind panel” guess — used to fake translucency without ARGB (no KWin blur ghosts).
_DESKTOP_BACKDROP_DARK = (30, 30, 36)
_DESKTOP_BACKDROP_LIGHT = (248, 248, 252)


def _blend_panel_opacity(
    surface_rgb: tuple[int, int, int],
    *,
    is_dark: bool,
    opacity: float,
) -> tuple[int, int, int]:
    """Blend surface toward a backdrop RGB. ``opacity`` 1 = solid surface, 0 = solid backdrop."""
    o = max(0.0, min(1.0, opacity))
    back = _DESKTOP_BACKDROP_DARK if is_dark else _DESKTOP_BACKDROP_LIGHT
    return tuple(
        min(255, max(0, round(surface_rgb[i] * o + back[i] * (1.0 - o)))) for i in range(3)
    )


def _system_stats_body(style: str, pal: MaterialPalette) -> str:
    """CPU/RAM section for bundled ``system`` preset (Conky ``cpubar`` / ``cpugraph`` syntax)."""
    prim = _hex6(pal, "primary", (0, 150, 150))
    sec = _hex6(pal, "secondary", (100, 100, 110))
    ter = _hex6(pal, "tertiary", (160, 160, 170))
    if style == "bar":
        return (
            "${color1}CPU ${cpu cpu0}%\n"
            "${cpubar cpu0 10,130}\n"
            "${color1}Load${alignr}${loadavg 1}\n"
            "${color1}RAM ${memperc}%\n"
            "${membar 10,130}\n"
            "${color3}${mem} / ${memmax}"
        )
    if style == "graph":
        return (
            f"${{color1}}CPU ${{cpu cpu0}}%\n"
            f"${{cpugraph cpu0 32,130 {prim} {sec}}}\n"
            f"${{color1}}Load${{alignr}}${{loadavg 1}}\n"
            f"${{color1}}RAM ${{memperc}}%\n"
            f"${{memgraph 32,130 {prim} {ter}}}\n"
            f"${{color3}}${{mem}} / ${{memmax}}"
        )
    return (
        "${color1}CPU${alignr}${cpu cpu0}%\n"
        "${color1}Load${alignr}${loadavg 1}\n"
        "${color1}RAM${alignr}${mem} / ${memmax}\n"
        "${color1}RAM %${alignr}${memperc}%"
    )


def build_render_context(pal: MaterialPalette, *, preset_id: str | None = None) -> dict[str, str]:
    ctx = dict(context_from_palette(pal))
    ctx["python_exec"] = shlex.quote(sys.executable)
    # Opaque dock window + blended panel colour: true ARGB translucency makes KWin blur the
    # wallpaper behind the panel; after overlaps that blur often fails to repaint (ghosting).
    surf = pal.colors.get("surface", (22, 22, 28))
    settings = load_conky_settings()
    opa = max(0.0, min(1.0, float(settings.conky_panel_opacity)))
    blended = _blend_panel_opacity(surf, is_dark=pal.is_dark, opacity=opa)
    ctx["panel_bg_hex6"] = rgb_to_hex(blended).lstrip("#")
    st = settings.system_stats_style
    if st not in ("text", "bar", "graph"):
        st = "text"
    ctx["system_stats_body"] = _system_stats_body(st, pal)
    ctx["system_min_width"] = "280" if st in ("bar", "graph") else "220"
    if preset_id is not None and preset_id in PRESETS:
        ctx["conky_alignment"] = alignment_for_preset(preset_id)
    else:
        ctx["conky_alignment"] = "top_left"
    return ctx


def render_preset(preset_id: str, pal: MaterialPalette) -> Path:
    """Write rendered ``~/.local/share/plasmacolorizer/conky/rendered/<id>.conf``."""
    if preset_id not in PRESETS:
        raise KeyError(f"Unknown preset: {preset_id}")
    raw = load_preset_template(preset_id)
    ctx = build_render_context(pal, preset_id=preset_id)
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
