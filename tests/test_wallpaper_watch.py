"""Wallpaper change fingerprint and watcher skip logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from plasmacolorizer.core.wallpaper_watch import (
    wallpaper_fingerprint_for_path,
    wallpaper_watch_skipped,
)


def test_wallpaper_fingerprint_stable_for_same_file(tmp_path: Path) -> None:
    img = tmp_path / "wall.jpg"
    img.write_bytes(b"same-content")
    fp1 = wallpaper_fingerprint_for_path(str(img))
    fp2 = wallpaper_fingerprint_for_path(str(img))
    assert fp1 == fp2
    assert str(img.resolve()) in fp1


def test_wallpaper_fingerprint_changes_on_content(tmp_path: Path) -> None:
    img = tmp_path / "wall.jpg"
    img.write_bytes(b"v1")
    fp1 = wallpaper_fingerprint_for_path(str(img))
    img.write_bytes(b"v2-longer")
    fp2 = wallpaper_fingerprint_for_path(str(img))
    assert fp1 != fp2


def test_wallpaper_watch_skipped_with_override() -> None:
    assert wallpaper_watch_skipped("") is False
    assert wallpaper_watch_skipped("  ") is False
    assert wallpaper_watch_skipped("/home/user/pinned.jpg") is True


def test_wallpaper_fingerprint_monitor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    img = tmp_path / "plasma-wall.png"
    img.write_bytes(b"wall")
    monkeypatch.setattr(
        "plasmacolorizer.core.wallpaper_watch.wp.current_wallpaper_image_path",
        lambda monitor, prefer_light=False: str(img),
    )
    from plasmacolorizer.core.wallpaper_watch import wallpaper_fingerprint

    assert wallpaper_fingerprint(0) == wallpaper_fingerprint_for_path(str(img))
