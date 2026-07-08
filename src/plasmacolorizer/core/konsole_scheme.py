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
# Mirror scheme name — toggled during live reload so Konsole picks up file changes.
KONSOLE_SCHEME_ALT_ID = "PlasmaColorizerAlt"


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
    return _blend(rgb, (255, 255, 255), 0.28)


def _faint(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return _blend(rgb, (0, 0, 0), 0.32)


def _token(
    colors: dict[str, tuple[int, int, int]],
    name: str,
    fallback: tuple[int, int, int],
) -> tuple[int, int, int]:
    return colors.get(name, fallback)


def _konsole_backgrounds(pal: MaterialPalette) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Background triple aligned with Material ``background`` / surface containers."""
    c = pal.colors
    bg = _token(c, "background", _token(c, "surface", (18, 18, 22)))
    if pal.is_dark:
        bg_i = _token(c, "surfaceContainerLow", _token(c, "surfaceContainer", bg))
        bg_f = _token(c, "surfaceContainer", _token(c, "surfaceContainerHigh", bg_i))
    else:
        bg_i = _token(c, "surfaceContainerHigh", _token(c, "surfaceContainer", bg))
        bg_f = _token(c, "surfaceContainer", _token(c, "surfaceContainerLow", bg_i))
    return bg, bg_i, bg_f


def _konsole_foregrounds(
    pal: MaterialPalette,
    bg: tuple[int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Default terminal text colours (normal / bold / dim)."""
    c = pal.colors
    fg = _token(c, "onBackground", _token(c, "onSurface", (220, 220, 230)))
    fg_f = _token(c, "onSurfaceVariant", _faint(fg))
    if pal.is_dark:
        fg_i = _token(c, "primaryFixed", _intense(fg))
    else:
        fg_i = _token(c, "primary", _intense(fg))
    return fg, fg_i, fg_f


def _konsole_ansi_sets(
    pal: MaterialPalette,
) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    """
    Sixteen-colour palette in Konsole layout (pywal / Material You style).

    ``Color0``–``Color7`` = normal ANSI; ``Color{i}Intense`` = bright ANSI;
    ``Color{i}Faint`` = dimmed normal.
    """
    c = pal.colors
    if pal.is_dark:
        normal = [
            _token(c, "surfaceContainerLowest", (20, 20, 26)),
            _token(c, "error", (220, 85, 95)),
            _token(c, "secondary", (95, 155, 105)),
            _token(c, "tertiary", (195, 165, 85)),
            _token(c, "primary", (105, 150, 205)),
            _token(c, "tertiaryContainer", (155, 95, 155)),
            _token(c, "secondaryFixed", (85, 185, 185)),
            _token(c, "outline", (125, 125, 135)),
        ]
        bright = [
            _token(c, "outlineVariant", (95, 95, 105)),
            _token(c, "errorContainer", (250, 145, 155)),
            _token(c, "secondaryFixed", (135, 205, 145)),
            _token(c, "tertiaryFixed", (225, 195, 115)),
            _token(c, "primaryFixed", (155, 195, 250)),
            _token(c, "onTertiaryFixed", (215, 155, 215)),
            _token(c, "onSecondaryFixed", (115, 215, 215)),
            _token(c, "onSurface", (230, 228, 238)),
        ]
    else:
        normal = [
            _token(c, "surfaceContainerHighest", (195, 195, 200)),
            _token(c, "error", (175, 45, 50)),
            _token(c, "secondary", (45, 105, 55)),
            _token(c, "tertiary", (125, 95, 25)),
            _token(c, "primary", (35, 75, 140)),
            _token(c, "tertiaryContainer", (115, 55, 115)),
            _token(c, "secondaryFixed", (25, 105, 105)),
            _token(c, "outline", (85, 85, 95)),
        ]
        bright = [
            _token(c, "onSurfaceVariant", (70, 70, 78)),
            _token(c, "onError", (95, 25, 28)),
            _token(c, "onSecondary", (15, 65, 25)),
            _token(c, "onTertiary", (65, 45, 8)),
            _token(c, "onPrimary", (12, 40, 85)),
            _token(c, "onTertiaryContainer", (55, 15, 55)),
            _token(c, "onSecondaryFixed", (8, 55, 55)),
            _token(c, "onSurface", (25, 25, 30)),
        ]
    faint = [_faint(rgb) for rgb in normal]
    return normal, bright, faint


def render_konsole_colorscheme(
    pal: MaterialPalette,
    *,
    scheme_id: str = KONSOLE_SCHEME_ID,
    opacity: float = 1.0,
    background_override: tuple[int, int, int] | None = None,
    foreground_override: tuple[int, int, int] | None = None,
) -> str:
    """Build Konsole ``.colorscheme`` INI text from a Material palette.

    ``opacity`` (0..1) drives the terminal background transparency; overrides
    replace the palette-derived background / foreground when supplied.
    """
    bg, bg_i, bg_f = _konsole_backgrounds(pal)
    fg, fg_i, fg_f = _konsole_foregrounds(pal, bg)
    normal, bright, faint = _konsole_ansi_sets(pal)
    if background_override is not None:
        bg = background_override
        bg_i = _intense(bg)
        bg_f = _faint(bg)
    if foreground_override is not None:
        fg = foreground_override
        fg_i = _intense(fg)
        fg_f = _faint(fg)
    op = max(0.0, min(1.0, float(opacity)))

    cfg = ConfigParser()
    cfg.optionxform = str
    cfg["Background"] = {"Color": _rgb_csv(bg)}
    cfg["BackgroundIntense"] = {"Color": _rgb_csv(bg_i)}
    cfg["BackgroundFaint"] = {"Color": _rgb_csv(bg_f)}
    cfg["Foreground"] = {"Color": _rgb_csv(fg)}
    cfg["ForegroundIntense"] = {"Color": _rgb_csv(fg_i)}
    cfg["ForegroundFaint"] = {"Color": _rgb_csv(fg_f)}
    for i, rgb in enumerate(normal):
        cfg[f"Color{i}"] = {"Color": _rgb_csv(rgb)}
        cfg[f"Color{i}Intense"] = {"Color": _rgb_csv(bright[i])}
        cfg[f"Color{i}Faint"] = {"Color": _rgb_csv(faint[i])}
    cfg["General"] = {
        "Description": scheme_id,
        "Opacity": f"{op:g}",
        "Blur": "true" if op < 1.0 else "false",
    }

    buf = StringIO()
    cfg.write(buf, space_around_delimiters=False)
    return buf.getvalue()


def write_konsole_colorscheme(
    pal: MaterialPalette,
    *,
    opacity: float = 1.0,
    background_override: tuple[int, int, int] | None = None,
    foreground_override: tuple[int, int, int] | None = None,
) -> Path:
    """Install primary + mirror Konsole schemes under ``~/.local/share/konsole/``."""
    kdir = konsole_dir()
    kdir.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        opacity=opacity,
        background_override=background_override,
        foreground_override=foreground_override,
    )
    primary = render_konsole_colorscheme(pal, scheme_id=KONSOLE_SCHEME_ID, **kwargs)
    alt = render_konsole_colorscheme(pal, scheme_id=KONSOLE_SCHEME_ALT_ID, **kwargs)
    path = kdir / f"{KONSOLE_SCHEME_ID}.colorscheme"
    path.write_text(primary, encoding="utf-8")
    (kdir / f"{KONSOLE_SCHEME_ALT_ID}.colorscheme").write_text(alt, encoding="utf-8")
    return path


def konsole_font_string(family: str, size: float) -> str:
    """Serialize ``family`` + point ``size`` into Konsole's ``Font=`` QFont string."""
    return f"{family},{size:g},-1,5,50,0,0,0,0,0"


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


def _ensure_konsole_mirror_profile(main_profile: str) -> Path:
    """Profile that only swaps ``ColorScheme`` to the mirror (for live reload)."""
    path = konsole_dir() / f"{KONSOLE_SCHEME_ALT_ID}.profile"
    cfg = ConfigParser()
    cfg.optionxform = str
    cfg["General"] = {"Name": KONSOLE_SCHEME_ALT_ID, "Parent": main_profile}
    cfg["Appearance"] = {"ColorScheme": KONSOLE_SCHEME_ALT_ID}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        cfg.write(fh, space_around_delimiters=False)
    return path


def patch_konsole_profile_color_scheme(
    profile_name: str | None = None,
    *,
    bold_intense: bool = True,
    font: str | None = None,
) -> Path:
    """Point the default (or named) Konsole profile at ``PlasmaColorizer`` colorscheme.

    Also toggles ``BoldIntenseColors`` and, when ``font`` is a Konsole QFont
    string (see :func:`konsole_font_string`), sets the profile ``Font``.
    """
    name = profile_name or read_default_konsole_profile_name()
    bold_value = "true" if bold_intense else "false"
    path = konsole_dir() / f"{name}.profile"
    if not path.is_file():
        cfg = ConfigParser()
        cfg.optionxform = str
        cfg["General"] = {"Name": name, "Parent": "FALLBACK/"}
        appearance = {
            "ColorScheme": KONSOLE_SCHEME_ID,
            "BoldIntenseColors": bold_value,
        }
        if font:
            appearance["Font"] = font
        cfg["Appearance"] = appearance
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            cfg.write(fh, space_around_delimiters=False)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = _replace_section_kv(text, "Appearance", "ColorScheme", KONSOLE_SCHEME_ID)
        text = _replace_section_kv(text, "Appearance", "BoldIntenseColors", bold_value)
        if font:
            text = _replace_section_kv(text, "Appearance", "Font", font)
        tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    _ensure_konsole_mirror_profile(name)
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


def _konsoleprofile_toggle() -> tuple[bool, str]:
    """Briefly apply mirror scheme so Konsole reloads colours from disk."""
    exe = shutil.which("konsoleprofile")
    if not exe:
        return False, "konsoleprofile not in PATH"
    try:
        subprocess.run(
            [exe, f"ColorScheme={KONSOLE_SCHEME_ALT_ID}"],
            check=False,
            capture_output=True,
            timeout=4,
        )
        subprocess.run(
            [exe, f"ColorScheme={KONSOLE_SCHEME_ID}"],
            check=False,
            capture_output=True,
            timeout=4,
        )
        return True, "konsoleprofile scheme toggle OK"
    except OSError as exc:
        return False, f"konsoleprofile: {exc}"


def reload_open_konsole_sessions(profile_name: str | None = None) -> tuple[bool, str]:
    """Reload colours on open Konsole windows by re-applying the profile via DBus."""
    profile = profile_name or read_default_konsole_profile_name()
    alt_profile = KONSOLE_SCHEME_ALT_ID
    parts: list[str] = []
    ok_any = False
    try:
        import dbus  # type: ignore

        bus = dbus.SessionBus()
        services = [
            s for s in (bus.list_names() or [])
            if "org.kde.konsole" in str(s)
        ]
        if not services:
            kp_ok, kp_msg = _konsoleprofile_toggle()
            parts.append(kp_msg)
            return kp_ok, "; ".join(parts)
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
                    current = str(siface.profile())
                    new_profile = alt_profile if current == profile else profile
                    siface.setProfile(new_profile)
                    count += 1
                except Exception:  # noqa: BLE001
                    continue
        if count:
            ok_any = True
            parts.append(f"reloaded {count} Konsole session(s)")
    except Exception as exc:  # noqa: BLE001
        parts.append(f"DBus: {exc}")

    kp_ok, kp_msg = _konsoleprofile_toggle()
    parts.append(kp_msg)
    ok_any = ok_any or kp_ok
    if not ok_any and not parts:
        return True, "no Konsole sessions updated"
    return ok_any, "; ".join(parts)


def apply_konsole_scheme(
    pal: MaterialPalette,
    *,
    profile_name: str | None = None,
    opacity: float = 1.0,
    background_override: tuple[int, int, int] | None = None,
    foreground_override: tuple[int, int, int] | None = None,
    bold_intense: bool = True,
    font: str | None = None,
) -> tuple[bool, str]:
    """Write colorscheme, patch default profile, and reload open Konsole windows."""
    parts: list[str] = []
    try:
        path = write_konsole_colorscheme(
            pal,
            opacity=opacity,
            background_override=background_override,
            foreground_override=foreground_override,
        )
        parts.append(f"wrote {path.name}")
        prof = patch_konsole_profile_color_scheme(
            profile_name,
            bold_intense=bold_intense,
            font=font,
        )
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
