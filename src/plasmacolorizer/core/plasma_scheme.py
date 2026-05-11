"""Generate Plasma `.colors` files and apply them to the running session.

Applying is done by:
  1. writing the `.colors` file to ~/.local/share/color-schemes/
  2. writing the same color sections (and `General/ColorScheme`) directly
     into ~/.config/kdeglobals
  3. emitting `org.kde.KGlobalSettings.notifyChange` on the session bus to
     refresh running apps (best-effort, with a timeout)

We deliberately do NOT invoke `plasma-apply-colorscheme` — it has been known
to hang for tens of seconds (or forever) when its DBus call to plasmashell
does not return, and it offers nothing we cannot do ourselves in-process.
"""

from __future__ import annotations

import os
import textwrap
import threading
from pathlib import Path

from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex


SCHEME_FILE_STEM = "PlasmaColorizer"

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


def apply_to_kdeglobals(pal: MaterialPalette) -> Path:
    """Write Material palette sections + General/ColorScheme into ~/.config/kdeglobals."""
    sections = build_color_sections(pal)

    text = _read_kdeglobals_text()
    text = _set_general_color_scheme(text, SCHEME_FILE_STEM)

    for section_name, rows in sections.items():
        body = _serialize_section(section_name, rows)
        text = _replace_or_append_section(text, f"[{section_name}]", body)

    path = kdeglobals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def notify_kde_palette_change(timeout: float = 2.0) -> tuple[bool, str]:
    """
    Ping KDE so running apps refresh their palette without relogin.

    Runs the DBus call in a worker thread with `timeout` seconds; if it
    doesn't return in time we bail out cleanly so the UI does not hang.
    """
    result: dict[str, object] = {"ok": False, "msg": ""}

    def worker() -> None:
        try:
            import dbus  # type: ignore
            bus = dbus.SessionBus()
            obj = bus.get_object("org.kde.KGlobalSettings", "/KGlobalSettings")
            iface = dbus.Interface(obj, "org.kde.KGlobalSettings")
            # PaletteChanged = 0, SettingsChanged = 0
            iface.notifyChange(0, 0)
            result["ok"] = True
            result["msg"] = "DBus notify sent."
        except Exception as exc:  # noqa: BLE001
            result["msg"] = f"DBus notify skipped: {exc}"

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False, f"DBus notify timed out after {timeout:.1f}s (ignored)"
    return bool(result["ok"]), str(result["msg"])


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
        "and notify_kde_palette_change() instead."
    )
