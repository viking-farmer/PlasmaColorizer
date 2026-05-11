"""Generate Plasma `.colors` files and apply them to the running session.

Applying is done by:
  1. writing the ``.colors`` file to ``~/.local/share/color-schemes/``
  2. writing the same color sections (and ``[General]`` keys) directly into
     ``~/.config/kdeglobals``, including ``ColorSchemeHash`` (SHA-1 of the
     scheme file) and disabling ``accentColorFromWallpaper`` so Plasma does
     not keep overriding accents from the wallpaper.
  3. installing a **Plasma desktop theme** under
     ``~/.local/share/plasma/desktoptheme/PlasmaColorizer/`` (a ``colors`` file
     plus ``metadata.json`` and a small ``plasmarc`` with ``FallbackTheme``)
     and setting ``~/.config/plasmarc`` ``[Theme] name=PlasmaColorizer``, so the
     shell (panel, Kickoff, widgets) reads the same palette — see KDE docs on
     Plasma Styles.
  4. calling ``org.kde.KWin.reconfigure`` and ``org.kde.PlasmaShell.refreshCurrentShell``
     on the session bus (Plasma 6 does not ship ``org.kde.KGlobalSettings``).

We deliberately do NOT invoke ``plasma-apply-colorscheme`` — it has been known
to hang for tens of seconds (or forever) when its DBus call to plasmashell
does not return.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex, rgb_tuple_to_argb_u


SCHEME_FILE_STEM = "PlasmaColorizer"
# User Plasma Style folder name (must match ``[Theme] name=`` in ``~/.config/plasmarc``).
DESKTOP_THEME_ID = SCHEME_FILE_STEM

# Material → KDE key mappings, shared by file generator + kdeglobals writer.
_WINDOW = {
    "BackgroundAlternate": "surfaceContainerHigh",
    "BackgroundNormal": "surfaceContainer",
    "DecorationFocus": "primary",
    "DecorationHover": "primaryDim",
    "ForegroundActive": "primary",
    "ForegroundInactive": "onSurfaceVariant",
    "ForegroundLink": "tertiary",
    "ForegroundNegative": "error",
    "ForegroundNeutral": "secondary",
    "ForegroundNormal": "onSurface",
    "ForegroundPositive": "secondary",
    "ForegroundVisited": "tertiary",
}
_VIEW = {
    "BackgroundAlternate": "surfaceContainerLow",
    "BackgroundNormal": "surface",
    "DecorationFocus": "primary",
    "DecorationHover": "primaryDim",
    "ForegroundActive": "primary",
    "ForegroundInactive": "onSurfaceVariant",
    "ForegroundLink": "primaryFixed",
    "ForegroundNegative": "error",
    "ForegroundNeutral": "secondary",
    "ForegroundNormal": "onSurface",
    "ForegroundPositive": "secondary",
    "ForegroundVisited": "tertiary",
}
_BUTTON = {
    "BackgroundAlternate": "surfaceContainerHighest",
    "BackgroundNormal": "surfaceContainerHigh",
    "DecorationFocus": "primary",
    "DecorationHover": "primaryDim",
    "ForegroundActive": "primary",
    "ForegroundInactive": "onSurfaceVariant",
    "ForegroundLink": "tertiary",
    "ForegroundNegative": "error",
    "ForegroundNeutral": "secondary",
    "ForegroundNormal": "onSurface",
    "ForegroundPositive": "secondary",
    "ForegroundVisited": "tertiary",
}
_SELECTION = {
    "BackgroundAlternate": "primaryDim",
    "BackgroundNormal": "primary",
    "DecorationFocus": "inversePrimary",
    "DecorationHover": "primaryDim",
    "ForegroundActive": "inverseOnSurface",
    "ForegroundInactive": "onSurfaceVariant",
    "ForegroundLink": "primaryFixedDim",
    "ForegroundNegative": "onErrorContainer",
    "ForegroundNeutral": "onSecondaryContainer",
    "ForegroundNormal": "onPrimary",
    "ForegroundPositive": "secondary",
    "ForegroundVisited": "tertiary",
}
_TOOLTIP = {
    "BackgroundAlternate": "surfaceContainer",
    "BackgroundNormal": "surfaceContainerHigh",
    "DecorationFocus": "primary",
    "DecorationHover": "primaryDim",
    "ForegroundActive": "primary",
    "ForegroundInactive": "onSurfaceVariant",
    "ForegroundLink": "tertiary",
    "ForegroundNegative": "error",
    "ForegroundNeutral": "secondary",
    "ForegroundNormal": "onSurface",
    "ForegroundPositive": "secondary",
    "ForegroundVisited": "tertiary",
}
_HEADER = {
    "BackgroundAlternate": "surfaceContainer",
    "BackgroundNormal": "surfaceContainerHigh",
    "DecorationFocus": "primary",
    "DecorationHover": "primaryDim",
    "ForegroundActive": "primary",
    "ForegroundInactive": "onSurfaceVariant",
    "ForegroundLink": "tertiary",
    "ForegroundNegative": "error",
    "ForegroundNeutral": "secondary",
    "ForegroundNormal": "onSurface",
    "ForegroundPositive": "secondary",
    "ForegroundVisited": "tertiary",
}
_HEADER_INACTIVE = {
    "BackgroundAlternate": "surfaceContainerHigh",
    "BackgroundNormal": "surfaceContainer",
    "DecorationFocus": "primary",
    "DecorationHover": "primaryDim",
    "ForegroundActive": "primary",
    "ForegroundInactive": "onSurfaceVariant",
    "ForegroundLink": "tertiary",
    "ForegroundNegative": "error",
    "ForegroundNeutral": "secondary",
    "ForegroundNormal": "onSurface",
    "ForegroundPositive": "secondary",
    "ForegroundVisited": "tertiary",
}


def scheme_install_dir() -> Path:
    return Path(os.path.expanduser("~/.local/share/color-schemes"))


def scheme_file_path() -> Path:
    return scheme_install_dir() / f"{SCHEME_FILE_STEM}.colors"


def kdeglobals_path() -> Path:
    return Path(os.path.expanduser("~/.config/kdeglobals"))


def plasma_desktop_theme_dir() -> Path:
    """``~/.local/share/plasma/desktoptheme/<DESKTOP_THEME_ID>/``."""
    return Path(os.path.expanduser(f"~/.local/share/plasma/desktoptheme/{DESKTOP_THEME_ID}"))


def user_plasmarc_path() -> Path:
    return Path(os.path.expanduser("~/.config/plasmarc"))


def read_current_plasma_desktop_theme_id() -> str | None:
    """Return the value of ``[Theme] name=`` from the user's ``plasmarc``, if set."""
    path = user_plasmarc_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    in_theme = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_theme = s.lower() == "[theme]"
            continue
        if in_theme and s.lower().startswith("name="):
            return s.split("=", 1)[1].strip()
    return None


def default_fallback_desktop_theme() -> str:
    """
    Plasma Style to inherit SVG/widget assets from when only ``colors`` is custom.

    Uses the user's *previous* shell theme from ``plasmarc`` when it is not our
    generated theme; otherwise picks the first installed system theme from a
    Manjaro-friendly list.
    """
    cur = read_current_plasma_desktop_theme_id()
    if cur and cur.casefold() != DESKTOP_THEME_ID.casefold():
        return cur
    for cand in ("breath-dark", "breath-light", "breath", "default", "breeze-dark", "breeze-light"):
        if (Path("/usr/share/plasma/desktoptheme") / cand).is_dir():
            return cand
    return "default"


def write_plasma_desktop_theme(pal: MaterialPalette) -> Path:
    """
    Install a Plasma **desktop theme** (Plasma Style) that reuses our palette.

    Panel, Kickoff, and other shell widgets read ``colors`` from the active
    desktop theme — not only ``kdeglobals``.  We ship a minimal theme folder
    (``colors`` + ``metadata.json`` + ``plasmarc`` with ``FallbackTheme``) so
    SVGs still resolve while colours follow Material You.
    """
    root = plasma_desktop_theme_dir()
    root.mkdir(parents=True, exist_ok=True)
    fallback = default_fallback_desktop_theme()
    (root / "colors").write_text(render_colors_file(pal), encoding="utf-8")

    meta = {
        "KPlugin": {
            "Id": DESKTOP_THEME_ID,
            "Name": "PlasmaColorizer",
            "Description": (
                "Material You colours generated by PlasmaColorizer; "
                f"SVG assets fall back to the {fallback!r} Plasma theme."
            ),
            "Category": "Plasma Theme",
            "License": "MIT",
            "Version": time.strftime("%Y%m%d.%H%M%S"),
            "EnabledByDefault": True,
            "Authors": [{"Name": "PlasmaColorizer"}],
        },
        "X-Plasma-API": "5.0",
    }
    (root / "metadata.json").write_text(json.dumps(meta, indent=4) + "\n", encoding="utf-8")

    theme_plasmarc = (
        f"[Settings]\nFallbackTheme={fallback}\n\n"
        "[ContrastEffect]\n"
        "enabled=true\n"
        "contrast=0.2\n"
        "intensity=0.6\n"
        "saturation=10\n\n"
        "[AdaptiveTransparency]\n"
        "enabled=true\n"
    )
    (root / "plasmarc").write_text(theme_plasmarc, encoding="utf-8")
    return root


def merge_user_plasmarc_select_desktop_theme(theme_id: str = DESKTOP_THEME_ID) -> Path:
    """Point ``~/.config/plasmarc`` ``[Theme] name=`` at our desktop theme."""
    path = user_plasmarc_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        text = ""
    body = f"[Theme]\nname={theme_id}\n"
    new_text = _replace_or_append_section(text, "[Theme]", body)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _rgb_csv(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"{r},{g},{b}"


def _resolve(mapping: dict[str, str], palette: dict[str, tuple[int, int, int]]) -> dict[str, str]:
    """Resolve a Material-token mapping into KDE 'r,g,b' strings."""
    return {kde_key: _rgb_csv(palette[mat_name]) for kde_key, mat_name in mapping.items()}


def build_color_sections(pal: MaterialPalette) -> dict[str, dict[str, str]]:
    """All KDE color sections to write to either the `.colors` file or kdeglobals."""
    c = pal.colors
    sections: dict[str, dict[str, str]] = {
        "ColorEffects:Disabled": {
            "Color": _rgb_csv(c["outline"]),
            "ColorAmount": "0",
            "ColorEffect": "0",
            "ContrastAmount": "0.65",
            "ContrastEffect": "1",
            "IntensityAmount": "0.1",
            "IntensityEffect": "2",
        },
        "ColorEffects:Inactive": {
            "ChangeSelectionColor": "true",
            "Color": _rgb_csv(c["outline"]),
            "ColorAmount": "0.025",
            "ColorEffect": "2",
            "ContrastAmount": "0.1",
            "ContrastEffect": "2",
            "Enable": "false",
            "IntensityAmount": "0",
            "IntensityEffect": "0",
        },
        "Colors:Button": _resolve(_BUTTON, c),
        "Colors:Complementary": _resolve(_WINDOW, c),
        "Colors:Header": _resolve(_HEADER, c),
        "Colors:Header][Inactive": _resolve(_HEADER_INACTIVE, c),
        "Colors:Selection": _resolve(_SELECTION, c),
        "Colors:Tooltip": _resolve(_TOOLTIP, c),
        "Colors:View": _resolve(_VIEW, c),
        "Colors:Window": _resolve(_WINDOW, c),
    }
    return sections


def render_colors_file(pal: MaterialPalette, *, display_name: str | None = None) -> str:
    """Build full `.colors` contents from Material palette."""
    name = display_name or "PlasmaColorizer"
    sections = build_color_sections(pal)

    parts: list[str] = []
    parts.append(textwrap.dedent(
        f"""\
        # SPDX-License-Identifier: MIT
        # Generated by PlasmaColorizer — seed accent {rgb_to_hex(pal.colors['primary'])}

        [General]
        ColorScheme={SCHEME_FILE_STEM}
        Name={name}

        """
    ))
    for section_name in sorted(sections.keys()):
        parts.append(f"[{section_name}]\n")
        rows = sections[section_name]
        for key in sorted(rows.keys()):
            parts.append(f"{key}={rows[key]}\n")
        parts.append("\n")
    return "".join(parts)


def write_scheme_file(contents: str) -> Path:
    dest_dir = scheme_install_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = scheme_file_path()
    path.write_text(contents, encoding="utf-8")
    return path


# ─── kdeglobals direct application ──────────────────────────────────────────

def _read_kdeglobals_text() -> str:
    path = kdeglobals_path()
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _serialize_section(name: str, rows: dict[str, str]) -> str:
    out = [f"[{name}]"]
    for k in sorted(rows.keys()):
        out.append(f"{k}={rows[k]}")
    return "\n".join(out) + "\n"


def _replace_or_append_section(text: str, section_header: str, new_section_body: str) -> str:
    """Replace lines from `section_header` up to next section, or append."""
    lines = text.splitlines(keepends=True)
    start = -1
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            start = i
            break

    if start == -1:
        if text and not text.endswith("\n"):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        return text + new_section_body

    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = j
            break

    return "".join(lines[:start]) + new_section_body + "".join(lines[end:])


def _set_general_color_scheme(text: str, scheme_name: str) -> str:
    """Ensure [General] has ColorScheme=<scheme_name> (replace if present, else add)."""
    lines = text.splitlines(keepends=True)
    in_general = False
    general_start = -1
    general_end = len(lines)
    cs_line_index = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped == "[General]":
                in_general = True
                general_start = i
                continue
            elif in_general:
                general_end = i
                break
        if in_general and stripped.lower().startswith("colorscheme="):
            cs_line_index = i

    new_cs = f"ColorScheme={scheme_name}\n"
    if cs_line_index != -1:
        lines[cs_line_index] = new_cs
        return "".join(lines)

    if general_start != -1:
        insert_at = general_start + 1
        return "".join(lines[:insert_at]) + new_cs + "".join(lines[insert_at:])

    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    return text + f"[General]\n{new_cs}"


def _set_general_kv(text: str, key: str, value: str) -> str:
    """Insert or replace ``key=value`` inside ``[General]`` (case-sensitive key)."""
    lines = text.splitlines(keepends=True)
    in_general = False
    general_start = -1
    general_end = len(lines)
    key_index = -1
    prefix = f"{key}="

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped == "[General]":
                in_general = True
                general_start = i
                continue
            elif in_general:
                general_end = i
                break
        if in_general and stripped.startswith(prefix):
            key_index = i
            break

    new_line = f"{key}={value}\n"
    if key_index != -1:
        lines[key_index] = new_line
        return "".join(lines)

    if general_start != -1:
        insert_at = general_start + 1
        return "".join(lines[:insert_at]) + new_line + "".join(lines[insert_at:])

    if text and not text.endswith("\n"):
        text += "\n"
    return text + f"[General]\n{new_line}"


def apply_to_kdeglobals(pal: MaterialPalette) -> Path:
    """Write Material palette sections + ``[General]`` keys into ``~/.config/kdeglobals``."""
    sections = build_color_sections(pal)

    text = _read_kdeglobals_text()
    text = _set_general_color_scheme(text, SCHEME_FILE_STEM)

    scheme_path = scheme_file_path()
    if scheme_path.is_file():
        digest = hashlib.sha1(scheme_path.read_bytes()).hexdigest()
        text = _set_general_kv(text, "ColorSchemeHash", digest)

    pri = pal.colors["primary"]
    text = _set_general_kv(text, "AccentColor", f"{pri[0]},{pri[1]},{pri[2]}")
    text = _set_general_kv(text, "accentColorFromWallpaper", "false")

    for section_name, rows in sections.items():
        body = _serialize_section(section_name, rows)
        text = _replace_or_append_section(text, f"[{section_name}]", body)

    path = kdeglobals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def notify_kde_palette_change(pal: MaterialPalette, *, timeout: float = 2.0) -> tuple[bool, str]:
    """
    Ask KWin, PlasmaShell, and the accent-color service to pick up ``kdeglobals``.

    ``org.kde.KGlobalSettings`` is not an activatable session service on
    Plasma 6 (Wayland).  We instead:

    * ``org.kde.KWin`` → ``reconfigure()`` (window chrome / compositor hints)
    * ``org.kde.plasmashell`` → ``refreshCurrentShell()`` (lightweight shell refresh)
    * ``org.kde.plasmashell.accentColor`` → ``setAccentColor(u)`` — this updates
      the **global Plasma accent** used by the panel, kickoff, and many shell
      widgets (see ``kded6`` module ``plasma_accentcolor_service``).

    The ``timeout`` parameter is kept for API compatibility; it is unused.
    """
    del timeout  # API compat; calls are synchronous and expected to be fast
    parts: list[str] = []
    ok_any = False
    try:
        import dbus  # type: ignore

        bus = dbus.SessionBus()
    except Exception as exc:  # noqa: BLE001
        return False, f"DBus session bus unavailable: {exc}"

    try:
        kwin = bus.get_object("org.kde.KWin", "/KWin")
        dbus.Interface(kwin, "org.kde.KWin").reconfigure()
        parts.append("KWin.reconfigure OK")
        ok_any = True
    except Exception as exc:  # noqa: BLE001
        parts.append(f"KWin.reconfigure: {exc}")

    try:
        shell = bus.get_object("org.kde.plasmashell", "/PlasmaShell")
        dbus.Interface(shell, "org.kde.PlasmaShell").refreshCurrentShell()
        parts.append("PlasmaShell.refreshCurrentShell OK")
        ok_any = True
    except Exception as exc:  # noqa: BLE001
        parts.append(f"PlasmaShell.refreshCurrentShell: {exc}")

    try:
        argb = rgb_tuple_to_argb_u(pal.colors["primary"])
        ac = bus.get_object("org.kde.plasmashell.accentColor", "/AccentColor")
        dbus.Interface(ac, "org.kde.plasmashell.accentColor").setAccentColor(dbus.UInt32(argb))
        parts.append("plasmashell.accentColor.setAccentColor OK")
        ok_any = True
    except Exception as exc:  # noqa: BLE001
        parts.append(f"plasmashell.accentColor.setAccentColor: {exc}")

    return ok_any, "; ".join(parts)


def restart_plasmashell(*, quit_timeout_s: float = 25.0) -> tuple[bool, str]:
    """
    Fully restart ``plasmashell`` so panel and launcher pick up every color role.

    ``refreshCurrentShell`` and accent updates help, but parts of the desktop
    shell still cache QPalette / theme data until the process restarts.  This
    matches what many KDE docs suggest when ``kdeglobals`` is edited by hand.

    Uses ``kquitapp6 plasmashell`` (or ``kquitapp5``) then ``kstart plasmashell``.
    There is a short desktop flicker while the shell comes back.
    """
    kquit = shutil.which("kquitapp6") or shutil.which("kquitapp5")
    kstart = shutil.which("kstart")
    if not kquit:
        return False, "Neither kquitapp6 nor kquitapp5 was found in PATH."
    if not kstart:
        return False, "kstart was not found in PATH."

    try:
        proc = subprocess.run(
            [kquit, "plasmashell"],
            capture_output=True,
            text=True,
            timeout=quit_timeout_s,
        )
        err_tail = (proc.stderr or proc.stdout or "").strip()
        if proc.returncode not in (0, 1):
            # 1 can mean "not running" on some setups; still try kstart
            if err_tail:
                parts = f"kquitapp returned {proc.returncode}: {err_tail[:200]}"
            else:
                parts = f"kquitapp returned {proc.returncode}"
        else:
            parts = "kquitapp plasmashell OK"
    except subprocess.TimeoutExpired:
        return False, f"{kquit} plasmashell timed out after {quit_timeout_s:.0f}s."

    subprocess.Popen(
        [kstart, "plasmashell"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True, f"{parts}; started plasmashell via {kstart}."


def apply_scheme() -> Path:
    """
    Apply the previously-built palette to the live KDE session.

    Side effects:
      • writes ~/.config/kdeglobals (the canonical store KDE reads)
      • sends a best-effort DBus notify so running apps refresh

    This function intentionally does not call plasma-apply-colorscheme,
    which has been observed to hang for tens of seconds on some KDE setups.
    """
    raise NotImplementedError(
        "apply_scheme() needs a MaterialPalette; call apply_to_kdeglobals(palette) "
        "and notify_kde_palette_change(palette) instead."
    )
