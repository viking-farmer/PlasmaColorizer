"""Generate Plasma `.colors` files and apply them."""

from __future__ import annotations

import os
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


def apply_scheme() -> None:
    exe = "plasma-apply-colorscheme"
    proc = subprocess.run(
        [exe, SCHEME_FILE_STEM],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"{exe} exited {proc.returncode}"
        raise RuntimeError(msg)
