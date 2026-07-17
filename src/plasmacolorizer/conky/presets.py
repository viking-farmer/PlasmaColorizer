"""Bundled Conky presets: load templates, render with palette, start/stop processes."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from shutil import which

from plasmacolorizer.conky.settings_store import load_conky_settings
from plasmacolorizer.conky.templating import context_from_palette, render_template
from plasmacolorizer.conky.themes import get_theme
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


def _escape_conky_text(value: str) -> str:
    """Neutralize Conky control sequences in user-provided text.

    ``$`` starts a variable (``${...}`` / ``$var``); ``$$`` emits a literal ``$``.
    Newlines would split one shortcut into several lines, so collapse them.
    """
    return value.replace("$", "$$").replace("\n", " ").replace("\r", " ").strip()


def _shortcuts_body(settings) -> str:
    """Render the editable shortcut rows as ``${color1}Label${alignr}Keys`` lines."""
    shortcuts = getattr(settings, "conky_shortcuts", None) or []
    lines: list[str] = []
    for sc in shortcuts:
        label = _escape_conky_text(str(getattr(sc, "label", "") or ""))
        keys = _escape_conky_text(str(getattr(sc, "keys", "") or ""))
        if not label and not keys:
            continue
        if keys:
            lines.append(f"${{color1}}{label}${{alignr}}{keys}")
        else:
            lines.append(f"${{color1}}{label}")
    return "\n".join(lines)


def _plasma_wayland_session() -> bool:
    """True when running under a Plasma Wayland session (XWayland Conky typical)."""
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("WAYLAND_SOCKET")):
        return False
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").upper()
    session = (os.environ.get("XDG_SESSION_DESKTOP") or "").lower()
    return "KDE" in desktop or session in ("plasma", "plasmawayland", "kde")


def resolve_conky_window_role(settings) -> tuple[str, str]:
    """Return ``(own_window_type, own_window_hints)`` for bundled presets.

    On Plasma Wayland, ``desktop``-type windows are drawn under plasmashell's
    wallpaper surface — Conky keeps running but is invisible (looks "dead").
    Prefer ``normal`` + ``below`` there so panels stay visible without covering
    real windows.
    """
    mode = str(getattr(settings, "conky_window_mode", "normal_below") or "normal_below").strip().lower()
    if mode == "desktop" and _plasma_wayland_session():
        mode = "normal_below"
    if mode == "desktop":
        return (
            "desktop",
            "undecorated,sticky,skip_taskbar,skip_pager",
        )
    return (
        "normal",
        "undecorated,below,sticky,skip_taskbar,skip_pager",
    )


def resolve_system_widget_style(settings) -> str:
    """Effective CPU/RAM widget style: theme override → user setting → ``text``."""
    theme = get_theme(getattr(settings, "conky_theme_id", None))
    style = theme.system_widget_style or getattr(settings, "system_stats_style", "text")
    if style not in ("text", "bar", "graph"):
        style = "text"
    return style


def build_render_context(pal: MaterialPalette, *, preset_id: str | None = None) -> dict[str, str]:
    ctx = dict(context_from_palette(pal))
    ctx["python_exec"] = shlex.quote(sys.executable)
    # Real ARGB transparency: ``own_window_argb_value`` drives the panel alpha
    # (slider lowest = 255, slider highest = 0).  The panel colour is the
    # palette surface so partial alpha shows the wallpaper through a tinted layer.
    surf = pal.colors.get("surface", (22, 22, 28))
    ctx["panel_bg_hex6"] = rgb_to_hex(surf).lstrip("#")
    settings = load_conky_settings()
    opa = max(0.0, min(1.0, float(settings.conky_panel_opacity)))
    ctx["conky_window_alpha"] = str(round(opa * 255))

    theme = get_theme(settings.conky_theme_id)
    ctx["theme_font_body"] = theme.font_body
    ctx["theme_title_open"] = theme.title_open
    ctx["theme_title_close"] = theme.title_close
    ctx["theme_section_divider"] = theme.section_divider

    style = resolve_system_widget_style(settings)
    ctx["system_stats_body"] = _system_stats_body(style, pal)
    ctx["system_min_width"] = "280" if style in ("bar", "graph") else "220"
    ctx["shortcuts_body"] = _shortcuts_body(settings)
    win_type, win_hints = resolve_conky_window_role(settings)
    ctx["conky_window_type"] = win_type
    ctx["conky_window_hints"] = win_hints
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


def _process_is_alive(pid: int) -> bool:
    """True if ``pid`` is a live (non-zombie) process we can signal."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # Zombies still answer kill(0); treat them as dead so the UI does not
    # claim Conky is running after it has already exited.
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            # Format: pid (comm) state ... — comm may contain spaces/parens.
            data = fh.read()
        rparen = data.rfind(")")
        if rparen != -1:
            state = data[rparen + 2 : rparen + 3]
            if state == "Z":
                return False
    except OSError:
        return False
    return True


def _pid_comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _pid_is_conky(pid: int) -> bool:
    return _pid_comm(pid) == "conky"


def is_preset_running(preset_id: str) -> bool:
    pf = _pid_file(preset_id)
    if not pf.is_file():
        return False
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
    except ValueError:
        pf.unlink(missing_ok=True)
        return False
    if not _process_is_alive(pid) or not _pid_is_conky(pid):
        pf.unlink(missing_ok=True)
        return False
    return True


def stop_preset(preset_id: str) -> tuple[bool, str]:
    """SIGTERM (then SIGKILL) the Conky instance we started for this preset."""
    pf = _pid_file(preset_id)
    if not pf.is_file():
        return True, "not running"
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
    except ValueError:
        pf.unlink(missing_ok=True)
        return True, "stale pid"
    if not _process_is_alive(pid):
        pf.unlink(missing_ok=True)
        return True, "already exited"
    if not _pid_is_conky(pid):
        pf.unlink(missing_ok=True)
        return True, f"stale pid {pid} (not conky)"
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pf.unlink(missing_ok=True)
        return True, "already exited"
    except PermissionError as exc:
        return False, str(exc)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not _process_is_alive(pid):
            break
        time.sleep(0.05)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and _process_is_alive(pid):
            time.sleep(0.05)

    pf.unlink(missing_ok=True)
    if _process_is_alive(pid):
        return False, f"failed to stop pid {pid}"
    return True, f"stopped pid {pid}"


def _opacity_to_cardinal(opacity: float) -> int:
    """Convert ``[0.0, 1.0]`` opacity into the 32-bit ``_NET_WM_WINDOW_OPACITY`` cardinal."""
    return int(round(max(0.0, min(1.0, float(opacity))) * 0xFFFFFFFF))


def _apply_window_opacity(
    window_title: str,
    opacity: float,
    *,
    timeout_s: float = 4.0,
    interval_s: float = 0.15,
) -> None:
    """Set ``_NET_WM_WINDOW_OPACITY`` on the named X11 window via ``xprop``.

    On KWin/Wayland (XWayland) the compositor often ignores Conky's
    ``own_window_argb_value`` even though the 32-bit visual is selected, so
    the panel ends up opaque regardless of the slider. ``_NET_WM_WINDOW_OPACITY``
    is the universal compositor opacity hint (KWin and Picom both honour it),
    so we apply it on top of the ARGB visual for reliable see-through panels.

    Runs in a daemon thread that retries until the window is mapped or
    ``timeout_s`` elapses, so callers never block on ``conky`` startup.
    Silently no-ops if ``xprop`` is missing or no X display is reachable.
    """
    cardinal = _opacity_to_cardinal(opacity)
    xprop = which("xprop")
    if not xprop:
        return

    def _worker() -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                r = subprocess.run(
                    [
                        xprop, "-name", window_title,
                        "-f", "_NET_WM_WINDOW_OPACITY", "32c",
                        "-set", "_NET_WM_WINDOW_OPACITY", str(cardinal),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=2,
                )
            except (OSError, subprocess.TimeoutExpired):
                return
            if r.returncode == 0:
                return
            time.sleep(interval_s)

    threading.Thread(target=_worker, daemon=True).start()


def apply_panel_opacity_to_running(opacity: float | None = None) -> None:
    """Push the current transparency setting to every running bundled Conky.

    Useful when the slider changes but a full re-render/restart is overkill —
    KWin honours the new ``_NET_WM_WINDOW_OPACITY`` value live.
    """
    if opacity is None:
        opacity = load_conky_settings().conky_panel_opacity
    for pid, meta in PRESETS.items():
        if is_preset_running(pid):
            _apply_window_opacity(meta.window_title, opacity)


def _kill_conky_for_config(cfg: Path) -> None:
    """SIGTERM any ``conky -c <cfg>`` processes (clears duplicate login/UI spawns)."""
    target = str(cfg)
    try:
        out = subprocess.run(
            ["pgrep", "-a", "-x", "conky"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return
    for line in (out.stdout or "").splitlines():
        if target not in line:
            continue
        try:
            pid = int(line.split(None, 1)[0])
        except ValueError:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue


def _spawn_conky(preset_id: str, cfg: Path) -> tuple[bool, str]:
    """Spawn a Conky process for ``cfg`` and record its pid (no ``-d`` so PID stays valid)."""
    bin_path = conky_binary()
    if not bin_path:
        return False, "conky executable not found in PATH"
    if is_preset_running(preset_id):
        stop_preset(preset_id)
    # Autostart + UI refresh can leave two Conkys on the same config; clear them.
    _kill_conky_for_config(cfg)
    time.sleep(0.15)
    log_path = conky_cache_dir() / f"{preset_id}.stderr.log"
    conky_cache_dir().mkdir(parents=True, exist_ok=True)
    try:
        log_fh = log_path.open("w", encoding="utf-8")
    except OSError:
        log_fh = subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            [bin_path, "-c", str(cfg)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log_fh,
            start_new_session=True,
        )
    except OSError as exc:
        if log_fh is not subprocess.DEVNULL:
            log_fh.close()
        return False, str(exc)
    if log_fh is not subprocess.DEVNULL:
        log_fh.close()

    # Brief settle: if Conky exits immediately (bad config / display), fail
    # loudly instead of leaving a zombie PID that looks "running".
    time.sleep(0.35)
    rc = proc.poll()
    if rc is not None:
        # Reap so we do not leave zombies when we are still the parent.
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        tail = ""
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-400:]
        except OSError:
            pass
        detail = f" (exit {rc})"
        if tail:
            detail += f": {tail}"
        return False, f"conky exited immediately{detail}"

    _pid_file(preset_id).write_text(str(proc.pid), encoding="utf-8")
    # Conky's own ARGB visual is unreliable under XWayland/KWin, so push the
    # universal _NET_WM_WINDOW_OPACITY hint as soon as the window is mapped.
    _apply_window_opacity(
        PRESETS[preset_id].window_title,
        load_conky_settings().conky_panel_opacity,
    )
    return True, f"started pid {proc.pid} ({cfg})"


def start_preset(preset_id: str, pal: MaterialPalette) -> tuple[bool, str]:
    """Render config from the palette and spawn ``conky -c …``."""
    if preset_id not in PRESETS:
        return False, f"unknown preset: {preset_id}"
    cfg = render_preset(preset_id, pal)
    return _spawn_conky(preset_id, cfg)


def start_preset_from_rendered(preset_id: str) -> tuple[bool, str]:
    """Spawn ``conky -c …`` using the last rendered config (used by login autostart)."""
    if preset_id not in PRESETS:
        return False, f"unknown preset: {preset_id}"
    cfg = rendered_dir() / f"{preset_id}.conf"
    if not cfg.is_file():
        return False, f"no rendered config at {cfg}; open PlasmaColorizer once to render"
    return _spawn_conky(preset_id, cfg)


# ---------------------------------------------------------------- autostart

_AUTOSTART_FILE_NAME = "plasmacolorizer-conky.desktop"


def autostart_dir() -> Path:
    return Path.home() / ".config/autostart"


def autostart_desktop_path() -> Path:
    return autostart_dir() / _AUTOSTART_FILE_NAME


def autostart_desktop_contents() -> str:
    """``.desktop`` entry that runs the autostart CLI with the current Python interpreter."""
    exe = shlex.quote(sys.executable)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=PlasmaColorizer Conky\n"
        "Comment=Re-launch the Conky presets that were running in the last session.\n"
        f"Exec={exe} -m plasmacolorizer.conky.autostart\n"
        "Icon=plasmacolorizer\n"
        "Terminal=false\n"
        "Hidden=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n"
    )


def install_autostart_entry() -> Path:
    """Write (or refresh) the autostart ``.desktop`` file. Returns its path."""
    path = autostart_desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(autostart_desktop_contents(), encoding="utf-8")
    return path


def uninstall_autostart_entry() -> bool:
    """Remove the autostart ``.desktop`` file (idempotent). True if a file was removed."""
    path = autostart_desktop_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def autostart_entry_installed() -> bool:
    return autostart_desktop_path().is_file()


def stop_all_presets() -> None:
    for pid in PRESETS:
        if is_preset_running(pid):
            stop_preset(pid)


def render_all_presets(pal: MaterialPalette) -> dict[str, Path]:
    """Render every bundled preset (does not start Conky)."""
    return {pid: render_preset(pid, pal) for pid in PRESETS}
