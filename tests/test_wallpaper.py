"""Wallpaper path resolution (especially KDE wallpaper *packages* as directories)."""

from __future__ import annotations

from pathlib import Path

from plasmacolorizer.core import wallpaper as wp


def test_resolve_package_dir_prefers_contents_images(tmp_path: Path) -> None:
    pkg = tmp_path / "MyWall"
    images = pkg / "contents" / "images"
    images.mkdir(parents=True)
    small = images / "small.png"
    large = images / "large.png"
    small.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
    large.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 4000)

    resolved = wp._path_from_plasma_wallpaper_package_dir(str(pkg), prefer_light=True)
    assert resolved is not None
    assert Path(resolved).suffix.lower() == ".png"
    assert Path(resolved).is_file()


def test_resolve_wallpaper_path_candidate_plain_file(tmp_path: Path) -> None:
    f = tmp_path / "x.jpg"
    f.write_bytes(b"not a real jpeg")
    out = wp._resolve_wallpaper_path_candidate(str(f), prefer_light=False)
    assert out == str(f.resolve())


def test_path_from_config_slide_paths(tmp_path: Path) -> None:
    pkg = tmp_path / "SlidePkg"
    images = pkg / "contents" / "images"
    images.mkdir(parents=True)
    img = images / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 20)

    wcfg = {"wallpaperPlugin": "org.kde.slideshow", "SlidePaths": [str(pkg)]}
    path = wp._path_from_config(wcfg, prefer_light=True)
    assert path is not None
    assert path.endswith(".png")
