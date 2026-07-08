"""Wallpaper change detection helpers."""

from __future__ import annotations

import os
from pathlib import Path

from plasmacolorizer.core import wallpaper as wp

WALLPAPER_POLL_INTERVAL_MS = 30_000
WALLPAPER_CHANGE_DEBOUNCE_MS = 5_000


def wallpaper_fingerprint_for_path(path: str) -> str:
    """Stable fingerprint for a resolved wallpaper image file."""
    p = Path(path)
    try:
        st = p.stat()
        return f"{p.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    except OSError:
        return str(p)


def wallpaper_fingerprint(monitor: int = 0, *, prefer_light: bool = False) -> str | None:
    """
    Return a fingerprint for the current Plasma wallpaper, or ``None`` if unresolved.

    Changes when the image file or slideshow slide changes.
    """
    try:
        path = wp.current_wallpaper_image_path(monitor, prefer_light=prefer_light)
    except (FileNotFoundError, OSError):
        return None
    return wallpaper_fingerprint_for_path(path)


def wallpaper_watch_skipped(manual_override: str) -> bool:
    """Skip auto-apply when the user pinned an explicit override path."""
    return bool(manual_override.strip())


def record_applied_wallpaper_fingerprint(
    src_path: str | None = None,
    *,
    monitor: int = 0,
) -> str | None:
    """Persist the fingerprint of the wallpaper we last applied successfully."""
    from plasmacolorizer.core.app_settings import load_app_settings, save_app_settings

    if src_path:
        fp = wallpaper_fingerprint_for_path(src_path)
    else:
        fp = wallpaper_fingerprint(monitor)
    if not fp:
        return None
    app = load_app_settings()
    if app.last_applied_wallpaper_fingerprint == fp:
        return fp
    app.last_applied_wallpaper_fingerprint = fp
    save_app_settings(app)
    return fp
