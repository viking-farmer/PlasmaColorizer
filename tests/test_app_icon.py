"""Icon assets ship in the package (Qt GUI tests need a display)."""

from __future__ import annotations

from importlib import resources


def test_icon_png_and_svg_shipped() -> None:
    root = resources.files("plasmacolorizer.icons")
    for size in (16, 22, 24, 32, 48, 64, 128, 256):
        assert (root / f"plasmacolorizer_{size}.png").is_file(), f"missing {size}px PNG"
    assert (root / "plasmacolorizer.svg").is_file()
