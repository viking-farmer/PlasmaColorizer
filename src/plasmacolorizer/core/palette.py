"""Material You palette generation from images and accent biasing."""

from __future__ import annotations

from dataclasses import dataclass

from materialyoucolor.dynamiccolor.color_spec import COLOR_NAMES
from materialyoucolor.dynamiccolor.material_dynamic_colors import MaterialDynamicColors
from materialyoucolor.hct import Hct
from materialyoucolor.quantize import ImageQuantizeCelebi
from materialyoucolor.scheme.scheme_tonal_spot import SchemeTonalSpot
from materialyoucolor.score.score import Score


@dataclass(frozen=True)
class MaterialPalette:
    """RGB tuples (0–255) keyed by Material dynamic color names."""

    is_dark: bool
    colors: dict[str, tuple[int, int, int]]

    def get(self, name: str) -> tuple[int, int, int]:
        return self.colors[name]

    def as_flat_hex(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in self.colors.items():
            out[f"{k}_hex"] = rgb_to_hex(v)
            out[k] = rgb_to_hex(v)
        return out


GREEN_TARGET_HUE = 125.0


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_tuple_to_argb_u(rgb: tuple[int, int, int]) -> int:
    """Pack opaque RGB into a 32-bit ``0xAARRGGBB`` value (DBus ``u`` / Qt-style)."""
    r, g, b = rgb
    return (255 << 24) | ((r & 255) << 16) | ((g & 255) << 8) | (b & 255)


def seed_color_from_image(path: str, quality: int = 4) -> int:
    """Return ARGB int suitable for Hct / dynamic scheme."""
    result = ImageQuantizeCelebi(path, max(1, int(quality)), 128)
    ranked = Score.score(result)
    if not ranked:
        raise ValueError(f"No seed color extracted from {path!r}")
    # Score.score returns sorted list of ARGB ints (library-dependent shape)
    if isinstance(ranked, dict):
        keys = list(ranked.keys())
        return int(keys[0])
    if isinstance(ranked, (list, tuple)):
        return int(ranked[0])
    return int(ranked)


def apply_green_bias(argb: int, strength: float) -> int:
    """Blend hue toward green; strength in [0, 1]."""
    if strength <= 0.0:
        return argb
    s = min(1.0, max(0.0, float(strength)))
    h = Hct.from_int(argb)
    new_h = h.hue + (GREEN_TARGET_HUE - h.hue) * s
    adjusted = Hct.from_hct(new_h, h.chroma, h.tone)
    return int(adjusted.to_int())


def build_palette(seed_argb: int, *, dark: bool, contrast: float = 0.0) -> MaterialPalette:
    hct = Hct.from_int(seed_argb)
    scheme = SchemeTonalSpot(hct, bool(dark), float(contrast), spec_version="2025")
    mdc = MaterialDynamicColors(spec="2025")
    colors: dict[str, tuple[int, int, int]] = {}
    for name in COLOR_NAMES:
        col = getattr(mdc, name)
        rgba = col.get_rgba(scheme)
        colors[name] = (int(rgba[0]), int(rgba[1]), int(rgba[2]))
    return MaterialPalette(is_dark=dark, colors=colors)
