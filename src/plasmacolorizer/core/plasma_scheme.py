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
  4. calling ``plasma-apply-colorscheme`` (with a reload stub) so Qt apps and Breeze
     decorations pick up ``Colors:View`` / ``Colors:Header``, then
     ``org.kde.KWin.reconfigure`` and ``org.kde.PlasmaShell.refreshCurrentShell``
     on the session bus (Plasma 6 does not ship ``org.kde.KGlobalSettings``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import textwrap
import time
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path

from materialyoucolor.dynamiccolor.color_spec import COLOR_NAMES

from plasmacolorizer.core.app_settings import AppSettings, load_app_settings, save_app_settings
from plasmacolorizer.core.component_colors import (
    ComponentColorOverride,
    apply_component_color_overrides as _apply_component_color_overrides,
    overrides_from_settings_dict,
)
from plasmacolorizer.core.dolphin_prefs import (
    dolphin_cohesion_warnings,
    patch_dolphin_follow_system_colorscheme,
)
from plasmacolorizer.core.konsole_scheme import apply_konsole_scheme, konsole_cohesion_warnings
from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex, rgb_tuple_to_argb_u

_MATERIAL_NAMES = frozenset(COLOR_NAMES)
_PRIMARY_TRIO = ("primary", "primaryDim", "onPrimary")
_ALLOWED_ACCENT = frozenset({"primary", "secondary", "tertiary", "primaryFixed"})
_ALLOWED_EMPHASIS = frozenset({"primary", "secondary", "tertiary"})
_ALLOWED_LINKS = frozenset({"tertiary", "primary", "secondary", "primaryFixed"})


@dataclass(frozen=True)
class SchemeApplyChoices:
    """Maps Material dynamic roles onto KDE chrome when writing the color scheme."""

    #: Replaces ``primary`` / ``primaryDim`` / ``onPrimary`` tokens in all KDE groups.
    accent: str = "primary"
    #: Replaces ``secondary`` / ``secondaryDim`` in neutral / positive foreground rows.
    emphasis: str = "secondary"
    #: When set, ``Colors:View`` link + visited foregrounds both use this Material token.
    links: str | None = None
    #: Use ``primaryContainer`` for panel/window backgrounds (stronger visible tint).
    strong_panel_tint: bool = False


def normalize_scheme_apply_choices(ch: SchemeApplyChoices | None) -> SchemeApplyChoices:
    if ch is None:
        return SchemeApplyChoices()
    a = ch.accent if ch.accent in _ALLOWED_ACCENT else "primary"
    e = ch.emphasis if ch.emphasis in _ALLOWED_EMPHASIS else "secondary"
    ln = ch.links if (ch.links is None or ch.links in _ALLOWED_LINKS) else None
    return SchemeApplyChoices(
        accent=a, emphasis=e, links=ln, strong_panel_tint=bool(ch.strong_panel_tint),
    )


def _accent_family_tokens(accent: str) -> tuple[str, str, str]:
    families = {
        "primary": _PRIMARY_TRIO,
        "secondary": ("secondary", "secondaryDim", "onSecondary"),
        "tertiary": ("tertiary", "tertiaryDim", "onTertiary"),
        "primaryFixed": ("primaryFixed", "primaryFixedDim", "onPrimaryFixed"),
    }
    return families.get(accent, _PRIMARY_TRIO)


def remap_material_token(mat: str, ch: SchemeApplyChoices | None) -> str:
    """Rewrite a Material token from our static tables according to user scheme choices."""
    if ch is None:
        return mat
    ch = normalize_scheme_apply_choices(ch)
    src = _PRIMARY_TRIO
    dst = _accent_family_tokens(ch.accent)
    primary_map = dict(zip(src, dst, strict=True))
    if mat in primary_map:
        return primary_map[mat]
    if mat == "inversePrimary" and ch.accent != "primary":
        return "inverseSurface"
    if mat == "secondary":
        return ch.emphasis
    if mat == "secondaryDim":
        dim = f"{ch.emphasis}Dim"
        return dim if dim in _MATERIAL_NAMES else "secondaryDim"
    return mat


SCHEME_FILE_STEM = "PlasmaColorizer"
# Alternate on-disk copy used to force ``plasma-apply-colorscheme`` to reload when the
# primary scheme name is unchanged (same trick as kde-material-you-colors).
SCHEME_RELOAD_STEM = "PlasmaColorizerReload"
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


def plasmashellrc_path() -> Path:
    return Path(os.path.expanduser("~/.config/plasmashellrc"))


def plasma_appletsrc_path() -> Path:
    return Path(os.path.expanduser("~/.config/plasma-org.kde.plasma.desktop-appletsrc"))


def kde_material_you_colors_config() -> Path:
    return Path(os.path.expanduser("~/.config/kde-material-you-colors/config.conf"))


def kwinrc_path() -> Path:
    return Path(os.path.expanduser("~/.config/kwinrc"))


def kdedefaults_path() -> Path:
    return Path(os.path.expanduser("~/.config/kdedefaults/kdeglobals"))


_PANEL_SECTION_RE = re.compile(r"^\[PlasmaViews\]\[Panel \d+\]$")


class PanelOpacityMode(IntEnum):
    """Plasma 6 ``panelOpacity`` in ``plasmashellrc`` — integer mode, not alpha."""

    ADAPTIVE = 0
    OPAQUE = 1
    TRANSLUCENT = 2


_PANEL_OPACITY_MODE_LABELS: dict[PanelOpacityMode, str] = {
    PanelOpacityMode.ADAPTIVE: "adaptive",
    PanelOpacityMode.OPAQUE: "opaque",
    PanelOpacityMode.TRANSLUCENT: "translucent",
}


def panel_opacity_mode_to_str(mode: PanelOpacityMode) -> str:
    return _PANEL_OPACITY_MODE_LABELS.get(mode, "opaque")


def str_to_panel_opacity_mode(value: str) -> PanelOpacityMode:
    key = (value or "").strip().lower()
    for mode, label in _PANEL_OPACITY_MODE_LABELS.items():
        if label == key:
            return mode
    return PanelOpacityMode.OPAQUE


def _parse_panel_opacity_raw(raw: str) -> PanelOpacityMode | None:
    """Parse ``panelOpacity`` value — int mode (Plasma 6) or legacy float."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        if "." in raw:
            fval = float(raw)
            if fval >= 1.0:
                return PanelOpacityMode.OPAQUE
            if fval <= 0.0:
                return PanelOpacityMode.TRANSLUCENT
            return PanelOpacityMode.ADAPTIVE
        ival = int(raw)
        if ival in (0, 1, 2):
            return PanelOpacityMode(ival)
    except ValueError:
        pass
    return None


def read_plasma_panel_opacity_mode() -> PanelOpacityMode | None:
    """Return the minimum opacity mode across all panels (``None`` if unset)."""
    path = plasmashellrc_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    modes: list[PanelOpacityMode] = []
    in_panel = False
    for line in text.splitlines():
        stripped = line.strip()
        if _PANEL_SECTION_RE.match(stripped):
            in_panel = True
            continue
        if stripped.startswith("[") and in_panel:
            in_panel = False
        if in_panel and stripped.lower().startswith("panelopacity="):
            parsed = _parse_panel_opacity_raw(stripped.split("=", 1)[1])
            if parsed is not None:
                modes.append(parsed)
    if not modes:
        return None
    return min(modes, key=lambda m: int(m))


def apply_plasma_panel_opacity_mode(mode: PanelOpacityMode) -> Path:
    """Write integer ``panelOpacity`` mode into every ``[PlasmaViews][Panel N]`` block."""
    opacity_s = str(int(mode))
    path = plasmashellrc_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        text = ""
    lines = text.splitlines(keepends=True) if text else []
    out: list[str] = []
    in_panel = False
    has_opacity = False
    for line in lines:
        stripped = line.strip()
        if _PANEL_SECTION_RE.match(stripped):
            if in_panel and not has_opacity:
                out.append(f"panelOpacity={opacity_s}\n")
            in_panel = True
            has_opacity = False
            out.append(line)
            continue
        if stripped.startswith("[") and in_panel:
            if not has_opacity:
                out.append(f"panelOpacity={opacity_s}\n")
            in_panel = False
            has_opacity = False
        if in_panel and stripped.lower().startswith("panelopacity="):
            out.append(f"panelOpacity={opacity_s}\n")
            has_opacity = True
            continue
        out.append(line)
    if in_panel and not has_opacity:
        out.append(f"panelOpacity={opacity_s}\n")
    new_text = "".join(out)
    if not new_text.endswith("\n") and new_text:
        new_text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)
    return path


#: Theme ``plasmarc`` sections that, if present, override the per-panel opacity
#: mode and must be stripped for Solid / Adaptive / Translucent to take effect.
_PANEL_OPACITY_BREAKING_SECTIONS = ("[AdaptiveTransparency]", "[ContrastEffect]")


def _strip_panel_opacity_breaking_sections(*, enabled: bool = False) -> tuple[bool, str]:
    """
    Remove sections from the installed theme ``plasmarc`` that override panel opacity.

    ``[AdaptiveTransparency]`` and ``[ContrastEffect]`` — even set to ``enabled=false``
    — make Plasma render every panel opacity mode identically. Stripping them repairs
    themes generated by older PlasmaColorizer versions. ``enabled`` is accepted for
    backwards compatibility and ignored.
    """
    del enabled
    path = plasma_desktop_theme_dir() / "plasmarc"
    if not path.is_file():
        return False, "PlasmaColorizer desktop theme not installed (apply a scheme first)"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"Could not read desktop theme plasmarc: {exc}"
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skipping = stripped in _PANEL_OPACITY_BREAKING_SECTIONS
        if skipping:
            continue
        out.append(line)
    new_text = "".join(out).rstrip() + "\n"
    if new_text == text:
        return True, "theme plasmarc already opacity-compatible"
    tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)
    live_ok, live_msg = apply_plasma_desktop_theme_live()
    return True, f"stripped opacity-breaking theme sections; {live_msg}"


# Backwards-compatible alias (older call sites / tests).
_patch_desktop_theme_adaptive_transparency = _strip_panel_opacity_breaking_sections


class DiagnosticSeverity(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class PanelOpacityDiagnostic:
    """One labelled check from :func:`run_panel_opacity_diagnostics`."""

    severity: DiagnosticSeverity
    category: str
    message: str

    def format_line(self) -> str:
        prefix = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}[self.severity.value]
        return f"[{prefix}] {self.category}: {self.message}"


def _theme_plasmarc_text() -> str | None:
    path = plasma_desktop_theme_dir() / "plasmarc"
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def theme_plasmarc_has_breaking_sections() -> bool:
    """Return True if the installed theme ``plasmarc`` contains opacity-breaking sections."""
    text = _theme_plasmarc_text()
    if text is None:
        return False
    return any(section in text for section in _PANEL_OPACITY_BREAKING_SECTIONS)


def theme_plasmarc_needs_repair() -> bool:
    """Return True if stripping opacity-breaking sections would change the theme ``plasmarc``."""
    path = plasma_desktop_theme_dir() / "plasmarc"
    text = _theme_plasmarc_text()
    if text is None or not path.is_file():
        return False
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skipping = stripped in _PANEL_OPACITY_BREAKING_SECTIONS
        if skipping:
            continue
        out.append(line)
    new_text = "".join(out).rstrip() + "\n"
    return new_text != text


def _read_panel_opacity_modes_by_panel() -> dict[str, PanelOpacityMode]:
    """Return ``panelOpacity`` per ``[PlasmaViews][Panel N]`` section name."""
    path = plasmashellrc_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    result: dict[str, PanelOpacityMode] = {}
    current_panel: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if _PANEL_SECTION_RE.match(stripped):
            current_panel = stripped.strip("[]").split("][")[-1]
            continue
        if stripped.startswith("[") and current_panel:
            current_panel = None
        if current_panel and stripped.lower().startswith("panelopacity="):
            parsed = _parse_panel_opacity_raw(stripped.split("=", 1)[1])
            if parsed is not None:
                result[current_panel] = parsed
    return result


def _kwin_blur_enabled() -> bool | None:
    """Return whether KWin's blur effect is enabled, or ``None`` if unknown."""
    path = kwinrc_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
            continue
        if section == "[effect-blur]" and stripped.lower().startswith("enabled="):
            return stripped.split("=", 1)[1].strip().lower() == "true"
        if section == "[plugins]" and stripped.lower().startswith("blur="):
            return stripped.split("=", 1)[1].strip().lower() == "true"
        if stripped.lower().startswith("blurenabled="):
            return stripped.split("=", 1)[1].strip().lower() == "true"
    return None


def run_panel_opacity_diagnostics(
    app_settings: AppSettings | None = None,
) -> list[PanelOpacityDiagnostic]:
    """Run structured checks for KDE panel opacity / translucency health."""
    app = app_settings or load_app_settings()
    lines: list[PanelOpacityDiagnostic] = []

    panel_modes = _read_panel_opacity_modes_by_panel()
    if panel_modes:
        summary = ", ".join(
            f"{name}={panel_opacity_mode_to_str(mode)} ({int(mode)})"
            for name, mode in sorted(panel_modes.items())
        )
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.PASS, "plasmashellrc", f"panelOpacity: {summary}",
        ))
    else:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.WARN,
            "plasmashellrc",
            "no panelOpacity keys found in plasmashellrc",
        ))

    ui_mode = str_to_panel_opacity_mode(app.plasma_panel_opacity_mode)
    sys_mode = read_plasma_panel_opacity_mode()
    if sys_mode is not None and sys_mode != ui_mode:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.WARN,
            "settings",
            f"app wants {panel_opacity_mode_to_str(ui_mode)} but plasmashellrc reports "
            f"{panel_opacity_mode_to_str(sys_mode)}",
        ))

    script = (
        "var s='';"
        "panels().forEach(function(p){"
        " s += 'id='+p.id+' loc='+p.location+' opacity='+p.opacity+' floating='+p.floating+'; ';"
        "});"
        "print(s || 'no panels');"
    )
    ok, out = run_plasma_shell_script(script)
    if ok:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.PASS, "live", out.strip() or "no panels reported",
        ))
    else:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.WARN, "live", f"could not query panels: {out}",
        ))

    cur_style = read_current_plasma_desktop_theme_id()
    if cur_style:
        sev = (
            DiagnosticSeverity.PASS
            if cur_style.casefold() == DESKTOP_THEME_ID.casefold()
            else DiagnosticSeverity.WARN
        )
        lines.append(PanelOpacityDiagnostic(
            sev, "plasma_style", f"active Plasma Style: {cur_style!r}",
        ))
    else:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.WARN, "plasma_style", "could not read plasmarc [Theme] name",
        ))

    theme_text = _theme_plasmarc_text()
    theme_path = plasma_desktop_theme_dir() / "plasmarc"
    if theme_text is None:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.WARN,
            "theme_plasmarc",
            "PlasmaColorizer desktop theme not installed (apply a scheme first)",
        ))
    elif theme_plasmarc_has_breaking_sections():
        found = [s for s in _PANEL_OPACITY_BREAKING_SECTIONS if s in theme_text]
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.FAIL,
            "theme_plasmarc",
            f"opacity-breaking sections present {found!r} — Solid / Adaptive / Translucent "
            "all render identically until repaired",
        ))
    else:
        extra_sections = [
            ln.strip()
            for ln in theme_text.splitlines()
            if ln.strip().startswith("[") and ln.strip().endswith("]")
            and ln.strip() != "[Settings]"
        ]
        if extra_sections:
            lines.append(PanelOpacityDiagnostic(
                DiagnosticSeverity.WARN,
                "theme_plasmarc",
                f"unexpected sections in {theme_path}: {extra_sections!r}",
            ))
        else:
            lines.append(PanelOpacityDiagnostic(
                DiagnosticSeverity.PASS,
                "theme_plasmarc",
                "minimal (only [Settings]/FallbackTheme) — opacity-compatible",
            ))

    if theme_plasmarc_needs_repair():
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.FAIL,
            "repair",
            "theme plasmarc needs repair (strip opacity-breaking sections)",
        ))
    else:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.PASS,
            "repair",
            "theme plasmarc does not need repair",
        ))

    for note in detect_competing_panel_tools():
        lines.append(PanelOpacityDiagnostic(DiagnosticSeverity.WARN, "competing_tool", note))

    blur = _kwin_blur_enabled()
    if blur is False:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.WARN,
            "kwin",
            "KWin blur is disabled — Translucent panels may look nearly opaque; "
            "enable blur in System Settings → Apps & Windows → Window Management → Desktop Effects",
        ))
    elif blur is True:
        lines.append(PanelOpacityDiagnostic(DiagnosticSeverity.PASS, "kwin", "blur effect enabled"))
    else:
        lines.append(PanelOpacityDiagnostic(
            DiagnosticSeverity.WARN, "kwin", "could not determine blur effect state",
        ))

    return lines


def format_panel_opacity_diagnostics(
    diagnostics: list[PanelOpacityDiagnostic] | None = None,
) -> list[str]:
    """Return human-readable diagnostic lines for logging."""
    items = diagnostics if diagnostics is not None else run_panel_opacity_diagnostics()
    return [d.format_line() for d in items]


def panel_opacity_diagnostics_need_repair(
    diagnostics: list[PanelOpacityDiagnostic] | None = None,
) -> bool:
    """Return True when diagnostics report the theme plasmarc needs repair."""
    items = diagnostics if diagnostics is not None else run_panel_opacity_diagnostics()
    return any(
        d.severity == DiagnosticSeverity.FAIL and d.category == "repair"
        for d in items
    )


def repair_plasma_theme_for_panel_opacity(
    *,
    restart_timeout_s: float = 25.0,
) -> tuple[bool, str]:
    """Strip opacity-breaking theme sections and restart plasmashell."""
    parts: list[str] = []
    strip_ok, strip_msg = _strip_panel_opacity_breaking_sections()
    parts.append(strip_msg)
    ok, rs_msg = restart_plasmashell(quit_timeout_s=restart_timeout_s)
    parts.append(rs_msg)
    return strip_ok and ok, "; ".join(parts)


def run_plasma_shell_script(script: str, *, timeout_s: float = 6.0) -> tuple[bool, str]:
    """Run a Plasma shell scripting snippet via ``PlasmaShell.evaluateScript`` (best-effort)."""
    try:
        import dbus  # type: ignore

        bus = dbus.SessionBus()
        shell = bus.get_object("org.kde.plasmashell", "/PlasmaShell")
        out = dbus.Interface(shell, "org.kde.PlasmaShell").evaluateScript(script)
        return True, str(out)
    except Exception as exc:  # noqa: BLE001
        return False, f"evaluateScript failed: {exc}"


def apply_panel_opacity_via_script(mode: PanelOpacityMode) -> tuple[bool, str]:
    """
    Set every panel's opacity live through the Plasma scripting API.

    Uses the ``Panel.opacity`` property (Plasma >= 6.2). Where supported this
    applies without a shell restart; on versions where the setter is a no-op it
    reports success but the value will not change (caller should verify/restart).
    """
    name = panel_opacity_mode_to_str(mode)
    script = (
        "var applied = 0;"
        "panels().forEach(function(p){ try { p.opacity = '%s'; applied += 1; } catch(e) {} });"
        "print(applied);"
    ) % name
    ok, out = run_plasma_shell_script(script)
    if not ok:
        return False, out
    return True, f"scripting set opacity={name} on {out.strip() or '0'} panel(s)"


def _panel_opacity_applied_via_script(mode: PanelOpacityMode) -> bool:
    """Return True if the live scripting API reports the desired mode on all panels."""
    want = panel_opacity_mode_to_str(mode)
    script = (
        "var ok = true;"
        "panels().forEach(function(p){ if (p.opacity !== '%s') ok = false; });"
        "print(ok ? 'yes' : 'no');"
    ) % want
    ok, out = run_plasma_shell_script(script)
    return ok and out.strip().endswith("yes")


def apply_plasma_panel_opacity_live(
    mode: PanelOpacityMode,
    *,
    restart_timeout_s: float = 25.0,
) -> tuple[bool, str]:
    """
    Persist panel opacity mode and make it visible.

    Strategy:
      1. Write the integer ``panelOpacity`` to ``plasmashellrc`` so the setting
         persists across logins.
      2. Ensure the desktop theme's ``[AdaptiveTransparency]`` is disabled — when
         enabled it overrides the per-panel opacity mode and makes all three
         choices render identically.
      3. Try the live Plasma scripting API (no flicker where supported).
      4. If scripting did not take effect, restart ``plasmashell`` — ``PanelView``
         only re-reads ``panelOpacity`` at startup, so this is the reliable path.
    """
    apply_plasma_panel_opacity_mode(mode)
    parts: list[str] = [
        f"plasmashellrc panelOpacity={int(mode)} ({panel_opacity_mode_to_str(mode)})",
    ]
    # Theme-level AdaptiveTransparency overrides the per-panel opacity mode, so it
    # must stay off for Solid / Adaptive / Translucent to have any visible effect.
    ad_ok, ad_msg = _patch_desktop_theme_adaptive_transparency(enabled=False)
    if not ad_ok:
        parts.append(ad_msg)

    script_ok, script_msg = apply_panel_opacity_via_script(mode)
    parts.append(script_msg)
    if script_ok and _panel_opacity_applied_via_script(mode):
        parts.append("applied live (no restart needed)")
        return True, "; ".join(parts)

    ok, restart_msg = restart_plasmashell(quit_timeout_s=restart_timeout_s)
    parts.append(restart_msg)
    return ok, "; ".join(parts)


def detect_competing_panel_tools() -> list[str]:
    """
    Detect third-party tools that repaint / override the Plasma panel background.

    When present, Plasma's native panel opacity mode is applied correctly but has
    no visible effect because these tools draw their own panel background.
    """
    warnings: list[str] = []
    try:
        applets = plasma_appletsrc_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        applets = ""
    if "luisbocanegra.kdematerialyou.colors" in applets or "luisbocanegra.panel.colorizer" in applets:
        warnings.append(
            "A luisbocanegra Material You / Panel Colorizer widget is on your panel. "
            "It paints the panel background itself, so Plasma's opacity mode has no visible "
            "effect until you remove that widget or disable its panel background/opacity option."
        )
    if kde_material_you_colors_config().is_file():
        warnings.append(
            "kde-material-you-colors is installed and may run a background service that "
            "restyles the panel. Pause it (tray menu → Pause) or disable its panel styling "
            "for the opacity mode to be visible."
        )
    return warnings


def reload_plasma_panel_config(
    mode: PanelOpacityMode | None = None,
    *,
    restart_timeout_s: float = 25.0,
) -> tuple[bool, str]:
    """Apply panel opacity live (writes config + restarts plasmashell)."""
    if mode is None:
        mode = read_plasma_panel_opacity_mode() or PanelOpacityMode.OPAQUE
    return apply_plasma_panel_opacity_live(mode, restart_timeout_s=restart_timeout_s)


def capture_plasma_fallback_theme(app: AppSettings) -> AppSettings:
    """Remember the user's Plasma Style id before we overwrite ``plasmarc``."""
    if app.plasma_fallback_theme_id:
        return app
    cur = read_current_plasma_desktop_theme_id()
    if cur and cur.casefold() != DESKTOP_THEME_ID.casefold():
        app = AppSettings(
            plasma_fallback_theme_id=cur,
            plasma_panel_opacity_mode=app.plasma_panel_opacity_mode,
            plasma_strong_panel_tint=app.plasma_strong_panel_tint,
            plasma_component_colors=app.plasma_component_colors,
        )
        save_app_settings(app)
    return app


def resolve_fallback_desktop_theme(app: AppSettings | None = None) -> str:
    """Plasma Style for ``FallbackTheme=`` — stored user theme, else adaptive default."""
    app = app or load_app_settings()
    stored = (app.plasma_fallback_theme_id or "").strip()
    if stored and stored.casefold() != DESKTOP_THEME_ID.casefold():
        if _desktop_theme_exists(stored):
            return stored
    cur = read_current_plasma_desktop_theme_id()
    if cur and cur.casefold() not in (DESKTOP_THEME_ID.casefold(), ""):
        if _desktop_theme_exists(cur):
            return cur
    # Prefer accent-adaptive themes (no bundled ``colors`` file).
    for cand in ("default", "breeze-light", "breeze-dark", "breath-light", "breath", "breath-dark"):
        if _desktop_theme_exists(cand) and not _theme_has_colors_file(cand):
            return cand
    for cand in ("default", "breeze-dark", "breeze-light", "breath-dark", "breath-light", "breath"):
        if _desktop_theme_exists(cand):
            return cand
    return "default"


def _desktop_theme_exists(theme_id: str) -> bool:
    local = Path.home() / ".local/share/plasma/desktoptheme" / theme_id
    if local.is_dir():
        return True
    return (Path("/usr/share/plasma/desktoptheme") / theme_id).is_dir()


def _theme_has_colors_file(theme_id: str) -> bool:
    for base in (
        Path.home() / ".local/share/plasma/desktoptheme" / theme_id,
        Path("/usr/share/plasma/desktoptheme") / theme_id,
    ):
        if (base / "colors").is_file():
            return True
    return False


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
    """Backward-compatible wrapper — prefer :func:`resolve_fallback_desktop_theme`."""
    return resolve_fallback_desktop_theme()


def write_plasma_desktop_theme(
    pal: MaterialPalette,
    *,
    choices: SchemeApplyChoices | None = None,
    adaptive_transparency_enabled: bool = False,
    fallback_theme_id: str | None = None,
    component_overrides: dict[str, ComponentColorOverride] | None = None,
) -> Path:
    """
    Install a Plasma **desktop theme** (Plasma Style) that reuses our palette.

    Panel, Kickoff, and other shell widgets read ``colors`` from the active
    desktop theme — not only ``kdeglobals``.  We ship a minimal theme folder
    (``colors`` + ``metadata.json`` + ``plasmarc`` with ``FallbackTheme``) so
    SVGs still resolve while colours follow Material You.
    """
    root = plasma_desktop_theme_dir()
    root.mkdir(parents=True, exist_ok=True)
    fallback = fallback_theme_id or resolve_fallback_desktop_theme()
    (root / "colors").write_text(
        render_colors_file(pal, choices=choices, component_overrides=component_overrides),
        encoding="utf-8",
    )

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

    # IMPORTANT: keep the theme ``plasmarc`` minimal (only ``FallbackTheme``).
    # Adding an ``[AdaptiveTransparency]`` or ``[ContrastEffect]`` section here — even
    # with ``enabled=false`` — makes Plasma render every panel opacity mode
    # identically, so the per-panel Solid / Adaptive / Translucent choice has no
    # visible effect. ``adaptive_transparency_enabled`` is retained for API
    # compatibility but intentionally ignored.
    del adaptive_transparency_enabled
    theme_plasmarc = f"[Settings]\nFallbackTheme={fallback}\n"
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


def _resolve(
    mapping: dict[str, str],
    palette: dict[str, tuple[int, int, int]],
    choices: SchemeApplyChoices | None,
) -> dict[str, str]:
    """Resolve a Material-token mapping into KDE 'r,g,b' strings."""
    return {
        kde_key: _rgb_csv(palette[remap_material_token(mat_name, choices)])
        for kde_key, mat_name in mapping.items()
    }


def build_color_sections(
    pal: MaterialPalette,
    choices: SchemeApplyChoices | None = None,
) -> dict[str, dict[str, str]]:
    """All KDE color sections to write to either the `.colors` file or kdeglobals."""
    ch = normalize_scheme_apply_choices(choices)
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
        "Colors:Button": _resolve(_BUTTON, c, ch),
        "Colors:Complementary": _resolve(_WINDOW, c, ch),
        "Colors:Header": _resolve(_HEADER, c, ch),
        "Colors:Header][Inactive": _resolve(_HEADER_INACTIVE, c, ch),
        "Colors:Selection": _resolve(_SELECTION, c, ch),
        "Colors:Tooltip": _resolve(_TOOLTIP, c, ch),
        "Colors:View": _resolve(_VIEW, c, ch),
        "Colors:Window": _resolve(_WINDOW, c, ch),
    }
    if ch.links:
        view = sections["Colors:View"]
        rgb = _rgb_csv(c[ch.links])
        view["ForegroundLink"] = rgb
        view["ForegroundVisited"] = rgb
    if ch.strong_panel_tint:
        pc = c.get("primaryContainer", c["surfaceContainer"])
        sch = c.get("surfaceContainerHigh", c["surfaceContainer"])
        for sec_name in ("Colors:Window", "Colors:Complementary", "Colors:Header", "Colors:Header][Inactive"):
            if sec_name in sections:
                sections[sec_name]["BackgroundNormal"] = _rgb_csv(pc)
                sections[sec_name]["BackgroundAlternate"] = _rgb_csv(sch)
    return sections


def render_colors_file(
    pal: MaterialPalette,
    *,
    display_name: str | None = None,
    choices: SchemeApplyChoices | None = None,
    component_overrides: dict[str, ComponentColorOverride] | None = None,
) -> str:
    """Build full `.colors` contents from Material palette."""
    name = display_name or "PlasmaColorizer"
    ch = normalize_scheme_apply_choices(choices)
    sections = build_color_sections(pal, ch)
    sections = _apply_component_color_overrides(
        sections, component_overrides, palette=pal,
    )
    accent_hex = rgb_to_hex(pal.colors[ch.accent])

    parts: list[str] = []
    parts.append(textwrap.dedent(
        f"""\
        # SPDX-License-Identifier: MIT
        # Generated by PlasmaColorizer — accent role {ch.accent} {accent_hex} (seed primary {rgb_to_hex(pal.colors['primary'])})

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
    _write_reload_scheme_stub(contents)
    return path


def _write_reload_scheme_stub(contents: str) -> Path:
    """Write a sibling ``.colors`` file so live apply can toggle-reload the scheme."""
    reload_body = contents.replace(
        f"Name={SCHEME_FILE_STEM}",
        f"Name={SCHEME_RELOAD_STEM}",
    )
    path = scheme_install_dir() / f"{SCHEME_RELOAD_STEM}.colors"
    path.write_text(reload_body, encoding="utf-8")
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


def apply_to_kdeglobals(
    pal: MaterialPalette,
    choices: SchemeApplyChoices | None = None,
    component_overrides: dict[str, ComponentColorOverride] | None = None,
) -> Path:
    """Write Material palette sections + ``[General]`` keys into ``~/.config/kdeglobals``."""
    ch = normalize_scheme_apply_choices(choices)
    sections = build_color_sections(pal, ch)
    sections = _apply_component_color_overrides(
        sections, component_overrides, palette=pal,
    )

    text = _read_kdeglobals_text()
    text = _set_general_color_scheme(text, SCHEME_FILE_STEM)

    scheme_path = scheme_file_path()
    if scheme_path.is_file():
        digest = hashlib.sha1(scheme_path.read_bytes()).hexdigest()
        text = _set_general_kv(text, "ColorSchemeHash", digest)

    pri = pal.colors[ch.accent]
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


@dataclass
class DiskApplyResult:
    """Outcome of writing scheme files and merging Plasma desktop theme metadata."""

    scheme_path: Path
    kdeglobals_path: Path | None
    apply_ok: bool
    apply_error: str = ""
    desktop_theme_path: Path | None = None
    desktop_theme_error: str = ""
    konsole_error: str = ""
    dolphin_error: str = ""
    dolphin_note: str = ""


def apply_material_palette_to_disk(
    pal: MaterialPalette,
    choices: SchemeApplyChoices | None = None,
    app_settings: AppSettings | None = None,
) -> DiskApplyResult:
    """Write ``.colors``, ``kdeglobals`` color sections, and install the desktop theme (best-effort)."""
    app = app_settings or load_app_settings()
    app = capture_plasma_fallback_theme(app)
    ch = normalize_scheme_apply_choices(choices)
    comp_overrides = overrides_from_settings_dict(app.plasma_component_colors)
    body = render_colors_file(pal, choices=ch, component_overrides=comp_overrides)
    scheme_path = write_scheme_file(body)
    try:
        kdg = apply_to_kdeglobals(pal, ch, component_overrides=comp_overrides)
    except Exception as exc:  # noqa: BLE001
        return DiskApplyResult(
            scheme_path=scheme_path,
            kdeglobals_path=None,
            apply_ok=False,
            apply_error=str(exc),
        )
    dpath: Path | None = None
    derr = ""
    try:
        mode = str_to_panel_opacity_mode(app.plasma_panel_opacity_mode)
        fallback = resolve_fallback_desktop_theme(app)
        dpath = write_plasma_desktop_theme(
            pal,
            choices=ch,
            adaptive_transparency_enabled=False,
            fallback_theme_id=fallback,
            component_overrides=comp_overrides,
        )
        merge_user_plasmarc_select_desktop_theme()
        # Belt-and-suspenders: repair any legacy opacity-breaking sections.
        _strip_panel_opacity_breaking_sections()
        apply_plasma_panel_opacity_mode(mode)
        _sync_kdedefaults_color_scheme(SCHEME_FILE_STEM)
    except Exception as exc:  # noqa: BLE001
        derr = str(exc)
    konsole_err = ""
    if app.apply_konsole_scheme:
        try:
            k_ok, k_msg = apply_konsole_scheme(pal)
            if not k_ok:
                konsole_err = k_msg
        except Exception as exc:  # noqa: BLE001
            konsole_err = str(exc)
    dolphin_err = ""
    dolphin_note = ""
    if app.dolphin_follow_system_colorscheme:
        try:
            d_ok, d_msg = patch_dolphin_follow_system_colorscheme()
            if d_ok:
                dolphin_note = d_msg
            else:
                dolphin_err = d_msg
        except Exception as exc:  # noqa: BLE001
            dolphin_err = str(exc)
    return DiskApplyResult(
        scheme_path=scheme_path,
        kdeglobals_path=kdg,
        apply_ok=True,
        apply_error="",
        desktop_theme_path=dpath,
        desktop_theme_error=derr,
        konsole_error=konsole_err,
        dolphin_error=dolphin_err,
        dolphin_note=dolphin_note,
    )


def _sync_kdedefaults_color_scheme(scheme_name: str) -> None:
    """Best-effort: align ``kdedefaults`` ``ColorScheme`` for next login."""
    path = kdedefaults_path()
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    new_text = _set_general_color_scheme(text, scheme_name)
    if new_text != text:
        tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, path)


def apply_plasma_desktop_theme_live(
    theme_id: str = DESKTOP_THEME_ID,
    *,
    timeout_s: float = 8.0,
) -> tuple[bool, str]:
    """Run ``plasma-apply-desktoptheme`` so plasmashell reloads shell widget colours."""
    exe = shutil.which("plasma-apply-desktoptheme")
    if not exe:
        return False, "plasma-apply-desktoptheme not found in PATH"
    try:
        proc = subprocess.run(
            [exe, theme_id],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"plasma-apply-desktoptheme timed out after {timeout_s:.0f}s"
    except OSError as exc:
        return False, f"plasma-apply-desktoptheme: {exc}"
    if proc.returncode == 0:
        return True, "plasma-apply-desktoptheme OK"
    err = (proc.stderr or proc.stdout or "").strip()
    tail = f": {err[:200]}" if err else ""
    return False, f"plasma-apply-desktoptheme returned {proc.returncode}{tail}"


def _run_plasma_apply_colorscheme(stem: str, *, timeout_s: float) -> tuple[bool, str]:
    exe = shutil.which("plasma-apply-colorscheme")
    if not exe:
        return False, "plasma-apply-colorscheme not found in PATH"
    colors_path = scheme_install_dir() / f"{stem}.colors"
    if not colors_path.is_file():
        return False, f"{colors_path.name} missing"
    try:
        proc = subprocess.run(
            [exe, stem],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"plasma-apply-colorscheme {stem} timed out after {timeout_s:.0f}s"
    except OSError as exc:
        return False, f"plasma-apply-colorscheme {stem}: {exc}"
    if proc.returncode == 0:
        return True, f"plasma-apply-colorscheme {stem} OK"
    err = (proc.stderr or proc.stdout or "").strip()
    tail = f": {err[:200]}" if err else ""
    return False, f"plasma-apply-colorscheme {stem} returned {proc.returncode}{tail}"


def apply_plasma_colorscheme_live(
    scheme_id: str = SCHEME_FILE_STEM,
    *,
    timeout_s: float = 8.0,
) -> tuple[bool, str]:
    """
    Apply the active Plasma color scheme so Qt apps (Dolphin, etc.) and Breeze
    decorations pick up ``Colors:View`` / ``Colors:Header``.

    ``plasma-apply-colorscheme`` ignores re-applying the same scheme name, so we
    briefly apply ``PlasmaColorizerReload`` first (kde-material-you-colors uses
    the same toggle trick).
    """
    parts: list[str] = []
    ok_any = False
    reload_path = scheme_install_dir() / f"{SCHEME_RELOAD_STEM}.colors"
    if reload_path.is_file() and scheme_id == SCHEME_FILE_STEM:
        rok, rmsg = _run_plasma_apply_colorscheme(
            SCHEME_RELOAD_STEM, timeout_s=min(4.0, timeout_s),
        )
        parts.append(rmsg)
        ok_any = ok_any or rok
    ok, msg = _run_plasma_apply_colorscheme(scheme_id, timeout_s=timeout_s)
    parts.append(msg)
    if ok or ok_any:
        _sync_colorscheme_hash_after_live_apply(scheme_id)
    return ok_any or ok, "; ".join(parts)


def _sync_colorscheme_hash_after_live_apply(scheme_id: str) -> None:
    """Keep ``ColorSchemeHash`` in kdeglobals aligned with the on-disk ``.colors`` file."""
    scheme_path = scheme_install_dir() / f"{scheme_id}.colors"
    if not scheme_path.is_file():
        return
    try:
        digest = hashlib.sha1(scheme_path.read_bytes()).hexdigest()
        text = _read_kdeglobals_text()
        new_text = _set_general_kv(text, "ColorSchemeHash", digest)
        if new_text == text:
            return
        path = kdeglobals_path()
        tmp = path.with_suffix(path.suffix + ".plasmacolorizer.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def toggle_reload_plasma_desktop_theme(
    *,
    theme_id: str = DESKTOP_THEME_ID,
    fallback_id: str | None = None,
) -> tuple[bool, str]:
    """Briefly switch Plasma Style away and back to force a theme cache flush."""
    fb = fallback_id or resolve_fallback_desktop_theme()
    try:
        merge_user_plasmarc_select_desktop_theme(fb)
        merge_user_plasmarc_select_desktop_theme(theme_id)
    except OSError as exc:
        return False, f"Plasma Style toggle failed: {exc}"
    return True, f"Plasma Style toggled {fb!r} → {theme_id!r}"


def collect_apply_diagnostics(app_settings: AppSettings | None = None) -> list[str]:
    """Return human-readable warnings about conditions that hide scheme colours."""
    app = app_settings or load_app_settings()
    warnings: list[str] = []
    cur = read_current_plasma_desktop_theme_id()
    if cur and cur.casefold() != DESKTOP_THEME_ID.casefold():
        warnings.append(
            f"Plasma Style in plasmarc is {cur!r} (expected {DESKTOP_THEME_ID!r}). "
            "Re-apply or pick PlasmaColorizer in System Settings → Appearance → Plasma Style."
        )
    mode = read_plasma_panel_opacity_mode()
    if mode == PanelOpacityMode.TRANSLUCENT:
        warnings.append(
            "Panel opacity mode is Translucent — custom colours may look faint through the wallpaper. "
            "Switch to Solid in PlasmaColorizer or panel settings for stronger tints."
        )
    elif mode == PanelOpacityMode.ADAPTIVE:
        warnings.append(
            "Panel opacity mode is Adaptive — the taskbar is translucent when no window touches it."
        )
    ui_mode = str_to_panel_opacity_mode(app.plasma_panel_opacity_mode)
    if ui_mode == PanelOpacityMode.TRANSLUCENT:
        warnings.append(
            "Panel opacity is set to Translucent — scheme tints may be hard to see on the taskbar."
        )
    try:
        applets = plasma_appletsrc_path().read_text(encoding="utf-8", errors="replace")
        if "luisbocanegra.kdematerialyou.colors" in applets:
            warnings.append(
                "Panel contains luisbocanegra.kdematerialyou.colors — it may override "
                "PlasmaColorizer accent colours independently."
            )
    except OSError:
        pass
    if kde_material_you_colors_config().is_file():
        warnings.append(
            "kde-material-you-colors is configured — it may compete with PlasmaColorizer accents."
        )
    for diag in run_panel_opacity_diagnostics(app):
        if diag.severity == DiagnosticSeverity.FAIL:
            warnings.append(f"Panel opacity: {diag.message}")
    for note in detect_competing_panel_tools():
        if note not in warnings:
            warnings.append(note)
    warnings.extend(konsole_cohesion_warnings())
    warnings.extend(dolphin_cohesion_warnings())
    try:
        kd_text = kdedefaults_path().read_text(encoding="utf-8", errors="replace")
        if "ColorScheme=PlasmaColorizer" not in kd_text and "colorscheme=plasmacolorizer" not in kd_text.lower():
            if "ColorScheme=" in kd_text:
                warnings.append(
                    "kdedefaults still references a different ColorScheme — "
                    "login may briefly restore the old scheme before PlasmaColorizer applies."
                )
    except OSError:
        pass
    return warnings


def notify_kde_palette_change(
    pal: MaterialPalette,
    *,
    timeout: float = 2.0,
    choices: SchemeApplyChoices | None = None,
) -> tuple[bool, str]:
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
    ch = normalize_scheme_apply_choices(choices)
    parts: list[str] = []
    ok_any = False

    cs_ok, cs_msg = apply_plasma_colorscheme_live()
    parts.append(cs_msg)
    ok_any = ok_any or cs_ok

    live_ok, live_msg = apply_plasma_desktop_theme_live()
    parts.append(live_msg)
    if live_ok:
        ok_any = True
    else:
        tr_ok, tr_msg = toggle_reload_plasma_desktop_theme()
        parts.append(tr_msg)
        ok_any = ok_any or tr_ok

    try:
        import dbus  # type: ignore

        bus = dbus.SessionBus()
    except Exception as exc:  # noqa: BLE001
        parts.append(f"DBus session bus unavailable: {exc}")
        return ok_any, "; ".join(parts)

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
        argb = rgb_tuple_to_argb_u(pal.colors[ch.accent])
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
