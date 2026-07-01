"""Dolphin color-scheme cohesion (follow global Plasma color scheme)."""

from __future__ import annotations

import os
import re
from pathlib import Path

# Left over from kde-material-you-colors; Dolphin will not follow kdeglobals while pinned.
_STALE_PINNED_SCHEMES = frozenset({
    "MaterialYou",
    "MaterialYouAlt",
    "MaterialYouDark",
    "MaterialYouLight",
    "Material You",
    "Material You Dark",
    "Material You Light",
})


def dolphinrc_path() -> Path:
    return Path(os.path.expanduser("~/.config/dolphinrc"))


def read_dolphin_pinned_scheme() -> str | None:
    """Return ``[UiSettings] ColorScheme`` from ``dolphinrc``, or ``None`` if unset."""
    path = dolphinrc_path()
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == "[UiSettings]"
            continue
        if in_section and stripped.lower().startswith("colorscheme="):
            return stripped.split("=", 1)[1].strip()
    return None


def _replace_section_kv(text: str, section: str, key: str, value: str) -> str:
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


def patch_dolphin_follow_system_colorscheme() -> tuple[bool, str]:
    """
    Point Dolphin at the global KDE color scheme (``ColorScheme=*``).

    Per-app pins (e.g. ``MaterialYouDark`` from kde-material-you-colors) block
    ``plasma-apply-colorscheme`` from reaching Dolphin's file view colours.
    """
    path = dolphinrc_path()
    prev = read_dolphin_pinned_scheme()
    if prev == "*":
        return True, "dolphinrc already follows system color scheme"
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = ""
        new_text = _replace_section_kv(text, "UiSettings", "ColorScheme", "*")
        tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        return False, f"dolphinrc patch failed: {exc}"
    if prev:
        return True, f"dolphinrc ColorScheme {prev!r} → *"
    return True, "dolphinrc ColorScheme set to * (follow system)"


def dolphin_cohesion_warnings() -> list[str]:
    pin = read_dolphin_pinned_scheme()
    if pin is None or pin == "*":
        return []
    stem = plasma_scheme_stem()
    if pin == stem:
        return []
    if is_stale_dolphin_pin(pin):
        return [
            f"Dolphin is pinned to color scheme {pin!r} in ~/.config/dolphinrc — "
            "re-apply with Dolphin theming enabled.",
        ]
    return [
        f"Dolphin uses its own color scheme {pin!r} instead of following the "
        "global Plasma scheme — file view colours will not track PlasmaColorizer.",
    ]


def plasma_scheme_stem() -> str:
    from plasmacolorizer.core.plasma_scheme import SCHEME_FILE_STEM

    return SCHEME_FILE_STEM


def is_stale_dolphin_pin(scheme: str | None) -> bool:
    if not scheme or scheme == "*":
        return False
    return scheme in _STALE_PINNED_SCHEMES or scheme.startswith("MaterialYou")
