"""Generate Plasma `.colors` files and apply them."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex


SCHEME_FILE_STEM = "PlasmaColorizer"


def scheme_install_dir() -> Path:
    return Path(os.path.expanduser("~/.local/share/color-schemes"))


def scheme_file_path() -> Path:
    return scheme_install_dir() / f"{SCHEME_FILE_STEM}.colors"


def _row(keys: dict[str, tuple[int, int, int]], mapping: dict[str, str]) -> dict[str, tuple[int, int, int]]:
    """Map logical KDE keys to RGB using Material token names."""
    out: dict[str, tuple[int, int, int]] = {}
    for kde_key, mat_name in mapping.items():
        out[kde_key] = keys[mat_name]
    return out


def _block(section: str, rows: dict[str, tuple[int, int, int]]) -> str:
    lines = [f"[{section}]"]
    for k in sorted(rows.keys()):
        r, g, b = rows[k]
        lines.append(f"{k}={r},{g},{b}")
    return "\n".join(lines) + "\n"


def _rgb_csv(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"{r},{g},{b}"


def render_colors_file(pal: MaterialPalette, *, display_name: str | None = None) -> str:
    """Build full `.colors` contents from Material palette."""
    c = pal.colors
    name = display_name or "PlasmaColorizer"

    # Shared chrome: focus and links track primary / tertiary
    window = _row(
        c,
        {
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
        },
    )
    view = _row(
        c,
        {
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
        },
    )
    button = _row(
        c,
        {
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
        },
    )
    selection = _row(
        c,
        {
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
        },
    )
    tooltip = _row(
        c,
        {
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
        },
    )
    complementary = window.copy()

    header = _row(
        c,
        {
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
        },
    )
    header_inactive = _row(
        c,
        {
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
        },
    )

    disabled = {
        "Color": _rgb_csv(c["outline"]),
        "ColorAmount": 0,
        "ColorEffect": 0,
        "ContrastAmount": 0.65,
        "ContrastEffect": 1,
        "IntensityAmount": 0.1,
        "IntensityEffect": 2,
    }
    inactive = {
        "ChangeSelectionColor": "true",
        "Color": _rgb_csv(c["outline"]),
        "ColorAmount": 0.025,
        "ColorEffect": 2,
        "ContrastAmount": 0.1,
        "ContrastEffect": 2,
        "Enable": "false",
        "IntensityAmount": 0,
        "IntensityEffect": 0,
    }

    # KDE also expects [Colors:Header][Inactive] nested section represented as Header][Inactive
    # Mirror Breeze structure: section name is literally Colors:Header][Inactive
    parts: list[str] = [
        textwrap.dedent(
            f"""\
            # SPDX-License-Identifier: MIT
            # Generated by PlasmaColorizer — seed accent {rgb_to_hex(c['primary'])}

            [General]
            ColorScheme={SCHEME_FILE_STEM}
            Name={name}
            """
        ).rstrip()
        + "\n\n",
        "[ColorEffects:Disabled]\n"
        + "\n".join(f"{k}={v}" for k, v in disabled.items())
        + "\n\n",
        "[ColorEffects:Inactive]\n"
        + "\n".join(f"{k}={v}" for k, v in inactive.items())
        + "\n\n",
        _block("Colors:Button", button),
        "\n",
        _block("Colors:Complementary", complementary),
        "\n",
        _block("Colors:Header", header),
        "\n",
        _block("Colors:Header][Inactive", header_inactive),
        "\n",
        _block("Colors:Selection", selection),
        "\n",
        _block("Colors:Tooltip", tooltip),
        "\n",
        _block("Colors:View", view),
        "\n",
        _block("Colors:Window", window),
        "\n",
    ]

    return "".join(parts)


def write_scheme_file(contents: str) -> Path:
    dest_dir = scheme_install_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = scheme_file_path()
    path.write_text(contents, encoding="utf-8")
    return path


def find_apply_colorscheme_executable() -> str:
    """Resolve `plasma-apply-colorscheme` — GUI apps often have a minimal PATH."""
    for name in ("plasma-apply-colorscheme", "plasma-apply-colorscheme6"):
        p = shutil.which(name)
        if p:
            return p
    for candidate in (
        "/usr/bin/plasma-apply-colorscheme",
        "/usr/local/bin/plasma-apply-colorscheme",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError(
        "plasma-apply-colorscheme was not found. Install the KDE Plasma workspace package "
        "(e.g. `plasma-workspace` on Arch/Manjaro) or run PlasmaColorizer from a full login session."
    )


def apply_scheme(timeout: int = 8) -> None:
    """
    Apply the scheme via plasma-apply-colorscheme.

    We redirect stdout/stderr to DEVNULL and kill the entire process group on
    timeout.  capture_output=True would leave pipes open when child DBus
    processes inherit them, making subprocess.communicate() block indefinitely
    even after the parent is killed.
    """
    import signal

    exe = find_apply_colorscheme_executable()
    proc = subprocess.Popen(
        [exe, SCHEME_FILE_STEM],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,   # own process group → we can kill all of it
    )
    try:
        retcode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        raise RuntimeError(
            f"{exe} did not finish within {timeout}s and was killed. "
            "Apply manually: plasma-apply-colorscheme PlasmaColorizer"
        )

    if retcode != 0:
        raise RuntimeError(f"{exe} exited with code {retcode}")
