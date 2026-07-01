"""Konsole color scheme generation and profile application."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from configparser import ConfigParser
from io import StringIO
from pathlib import Path

from plasmacolorizer.core.palette import MaterialPalette

KONSOLE_SCHEME_ID = "PlasmaColorizer"


def konsole_dir() -> Path:
    return Path(os.path.expanduser("~/.local/share/konsole"))


def konsolerc_path() -> Path:
    return Path(os.path.expanduser("~/.config/konsolerc"))


def _rgb_csv(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]},{rgb[1]},{rgb[2]}"


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _intense(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return _blend(rgb, (255, 255, 255), 0.25)


def _faint(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return _blend(rgb, (0, 0, 0), 0.35)


def _ansi_palette(pal: MaterialPalette) -> list[tuple[int, int, int]]:
    """Sixteen base ANSI colors mapped from Material tokens."""
    c = pal.colors
    return [
        c.get("surfaceContainerLowest", c.get("surface", (30, 30, 36))),
        c.get("error", (200, 50, 50)),
        c.get("tertiary", (90, 100, 110)),
        c.get("secondary", (80, 90, 100)),
        c.get("primary", (100, 120, 140)),
        c.get("outline", (100, 100, 110)),
        c.get("primaryFixed", (110, 130, 150)),
        c.get("onSurface", (200, 200, 210)),
        c.get("onSurfaceVariant", (150, 150, 160)),
        c.get("onError", (30, 10, 10)),
        c.get("onTertiary", (20, 20, 30)),
        c.get("onSecondary", (20, 20, 30)),
        c.get("onPrimary", (10, 10, 20)),
        c.get("inversePrimary", (180, 180, 190)),
        c.get("inverseOnSurface", (30, 30, 40)),
        c.get("surfaceContainerHighest", (35, 35, 40)),
    ]


def render_konsole_colorscheme(pal: MaterialPalette) -> str:
    """Build Konsole ``.colorscheme`` INI text from a Material palette."""
    c = pal.colors
    bg = c.get("surfaceContainerLow", c.get("surface", (20, 22, 24)))
    bg_i = c.get("surfaceContainer", bg)
    bg_f = c.get("surfaceContainerHigh", bg_i)
    fg = c.get("onSurface", (220, 220, 230))
    fg_i = _intense(fg)
    fg_f = _faint(fg)
    ansi = _ansi_palette(pal)

    cfg = ConfigParser()
    cfg.optionxform = str
    cfg["Background"] = {"Color": _rgb_csv(bg)}
    cfg["BackgroundIntense"] = {"Color": _rgb_csv(bg_i)}
    cfg["BackgroundFaint"] = {"Color": _rgb_csv(bg_f)}
    cfg["Foreground"] = {"Color": _rgb_csv(fg)}
    cfg["ForegroundIntense"] = {"Color": _rgb_csv(fg_i)}
    cfg["ForegroundFaint"] = {"Color": _rgb_csv(fg_f)}
    for i, rgb in enumerate(ansi):
        cfg[f"Color{i}"] = {"Color": _rgb_csv(rgb)}
        cfg[f"Color{i}Intense"] = {"Color": _rgb_csv(_intense(rgb))}
        cfg[f"Color{i}Faint"] = {"Color": _rgb_csv(_faint(rgb))}
    cfg["General"] = {
        "Description": KONSOLE_SCHEME_ID,
        "Opacity": "1.0",
        "Blur": "false",
    }

    buf = StringIO()
    cfg.write(buf, space_around_delimiters=False)
    return buf.getvalue()


def write_konsole_colorscheme(pal: MaterialPalette) -> Path:
    """Install ``PlasmaColorizer.colorscheme`` under ``~/.local/share/konsole/``."""
    kdir = konsole_dir()
    kdir.mkdir(parents=True, exist_ok=True)
    path = kdir / f"{KONSOLE_SCHEME_ID}.colorscheme"
    path.write_text(render_konsole_colorscheme(pal), encoding="utf-8")
    return path


def read_default_konsole_profile_name() -> str:
    """Return default profile name without ``.profile`` suffix."""
    rc = konsolerc_path()
    if not rc.is_file():
        return "Profile 1"
    try:
        text = rc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "Profile 1"
    for line in text.splitlines():
        if line.strip().startswith("DefaultProfile="):
            part = line.split("=", 1)[1].strip()
            if part:
                return part.replace(".profile", "")
    return "Profile 1"


def _replace_section_kv(text: str, section: str, key: str, value: str) -> str:
    """Replace or append ``key=value`` inside ``[section]``."""
    header = f"[{section}]"
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_section = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not replaced:
                out.append(f"{key}={value}\n")
                replaced = True
            in_section = stripped == header
            out.append(line)
            continue
        if in_section and stripped.lower().startswith(f"{key.lower()}="):
            out.append(f"{key}={value}\n")
            replaced = True
            continue
        out.append(line)
    if in_section and not replaced:
        out.append(f"{key}={value}\n")
    if header not in text:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(f"{header}\n{key}={value}\n")
    return "".join(out)


def patch_konsole_profile_color_scheme(profile_name: str | None = None) -> Path:
    """Point the default (or named) Konsole profile at ``PlasmaColorizer`` colorscheme."""
    name = profile_name or read_default_konsole_profile_name()
    path = konsole_dir() / f"{name}.profile"
    if not path.is_file():
        cfg = ConfigParser()
        cfg.optionxform = str
        cfg["General"] = {"Name": name, "Parent": "FALLBACK/"}
        cfg["Appearance"] = {"ColorScheme": KONSOLE_SCHEME_ID}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            cfg.write(fh, space_around_delimiters=False)
        return path
    text = path.read_text(encoding="utf-8", errors="replace")
    new_text = _replace_section_kv(text, "Appearance", "ColorScheme", KONSOLE_SCHEME_ID)
    tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _konsole_profile_uses_stale_scheme(profile_name: str | None = None) -> bool:
    name = profile_name or read_default_konsole_profile_name()
    path = konsole_dir() / f"{name}.profile"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    m = re.search(r"^ColorScheme=(.+)$", text, re.MULTILINE)
    if not m:
        return False
    scheme = m.group(1).strip()
    return scheme in ("MaterialYou", "MaterialYouAlt")


def reload_open_konsole_sessions(profile_name: str | None = None) -> tuple[bool, str]:
    """Reload colors on open Konsole windows by re-applying the profile via DBus."""
    profile = profile_name or read_default_konsole_profile_name()
    try:
        import dbus  # type: ignore

        bus = dbus.SessionBus()
        services = [
            s for s in (bus.list_names() or [])
            if "org.kde.konsole" in str(s)
        ]
        if not services:
            return True, "no open Konsole sessions"
        count = 0
        for service in services:
            try:
                obj = bus.get_object(str(service), "/")
                iface = dbus.Interface(obj, "org.freedesktop.DBus.Introspectable")
                intro = iface.Introspect()
            except Exception:  # noqa: BLE001
                continue
            for match in re.finditer(r'object path="(/Sessions/\d+)"', intro):
                session_path = match.group(1)
                try:
                    session = bus.get_object(str(service), session_path)
                    siface = dbus.Interface(session, "org.kde.konsole.Session")
                    siface.setProfile(profile)
                    count += 1
                except Exception:  # noqa: BLE001
                    continue
        if count:
            return True, f"reloaded {count} Konsole session(s)"
    except Exception as exc:  # noqa: BLE001
        exe = shutil.which("konsoleprofile")
        if exe:
            try:
                subprocess.run(
                    [exe, f"ColorScheme={KONSOLE_SCHEME_ID}"],
                    check=False,
                    capture_output=True,
                    timeout=4,
                )
                return True, f"konsoleprofile ColorScheme={KONSOLE_SCHEME_ID} (DBus: {exc})"
            except OSError as sub_exc:
                return False, f"Konsole reload failed: {exc}; {sub_exc}"
        return False, f"Konsole DBus reload failed: {exc}"
    return True, "no Konsole sessions updated"


def apply_konsole_scheme(pal: MaterialPalette, *, profile_name: str | None = None) -> tuple[bool, str]:
    """Write colorscheme, patch default profile, and reload open Konsole windows."""
    parts: list[str] = []
    try:
        path = write_konsole_colorscheme(pal)
        parts.append(f"wrote {path.name}")
        prof = patch_konsole_profile_color_scheme(profile_name)
        parts.append(f"profile {prof.name}")
    except OSError as exc:
        return False, str(exc)
    ok, msg = reload_open_konsole_sessions(profile_name)
    parts.append(msg)
    return ok, "; ".join(parts)


def konsole_cohesion_warnings() -> list[str]:
    """Return warnings when Konsole still references kde-material-you schemes."""
    if _konsole_profile_uses_stale_scheme():
        name = read_default_konsole_profile_name()
        return [
            f"Konsole default profile {name!r} still uses MaterialYou/MaterialYouAlt — "
            "re-apply with Konsole theming enabled or run Apply palette to Konsole.",
        ]
    return []
