"""Headless generate+apply pipeline shared by the UI worker and wallpaper daemon."""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from plasmacolorizer.core import wallpaper as wp
from plasmacolorizer.core.app_settings import AppSettings, load_app_settings
from plasmacolorizer.core.logger import get_logger
from plasmacolorizer.core.palette import MaterialPalette
from plasmacolorizer.core import plasma_scheme
from plasmacolorizer.core.plasma_scheme import DiskApplyResult, SchemeApplyChoices
from plasmacolorizer.workers import compute_material_palette_from_wallpaper


APPLY_LOCK_PATH = Path(
    os.path.expanduser("~/.cache/plasmacolorizer/apply.lock"),
)


@dataclass
class PipelineResult:
    src: str
    palette: MaterialPalette
    disk: DiskApplyResult
    notify_ok: bool
    notify_msg: str
    restarted_plasma: bool = False
    restart_msg: str = ""


def scheme_choices_from_settings(app: AppSettings) -> SchemeApplyChoices:
    links = app.scheme_links.strip() if app.scheme_links else None
    if links == "":
        links = None
    return SchemeApplyChoices(
        accent=app.scheme_accent or "primary",
        emphasis=app.scheme_emphasis or "secondary",
        links=links,
        strong_panel_tint=app.plasma_strong_panel_tint,
    )


def dark_mode_from_settings(app: AppSettings) -> bool | None:
    mode = (app.dark_mode or "follow").strip().lower()
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return None


@contextmanager
def apply_lock():
    """Serialize disk apply between the UI and the wallpaper daemon."""
    APPLY_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = APPLY_LOCK_PATH.open("a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def resolve_wallpaper_for_apply(
    app: AppSettings,
    *,
    src_path: str | None = None,
) -> str:
    if src_path:
        path = Path(src_path)
        if not path.is_file():
            raise FileNotFoundError(f"Wallpaper image not found: {src_path}")
        return str(path)
    return wp.current_wallpaper_image_path(app.wallpaper_monitor)


def generate_and_apply_from_wallpaper(
    *,
    src_path: str | None = None,
    app_settings: AppSettings | None = None,
    log_prefix: str = "",
) -> PipelineResult:
    """Quantize wallpaper, write scheme files, and refresh the live KDE session."""
    log = get_logger()
    app = app_settings or load_app_settings()
    prefix = f"{log_prefix} " if log_prefix else ""
    src = resolve_wallpaper_for_apply(app, src_path=src_path)
    choices = scheme_choices_from_settings(app)
    dark = dark_mode_from_settings(app)

    with apply_lock():
        log.info("%sgenerate+apply from %s", prefix, src)
        palette = compute_material_palette_from_wallpaper(
            src_path=src,
            primary_bias_strength=app.primary_bias_strength,
            dark=dark,
            quality=app.quantizer_quality,
            log=log,
        )
        disk = plasma_scheme.apply_material_palette_to_disk(
            palette, choices, app_settings=app,
        )
        if not disk.apply_ok:
            return PipelineResult(
                src=src,
                palette=palette,
                disk=disk,
                notify_ok=False,
                notify_msg=disk.apply_error,
            )

        notify_ok, notify_msg = plasma_scheme.notify_kde_palette_change(
            palette,
            choices=choices,
        )
        restarted = False
        restart_msg = ""
        if app.restart_plasma_after_apply or app.plasma_panel_opacity_mode != "opaque":
            restarted, restart_msg = plasma_scheme.restart_plasmashell()

    return PipelineResult(
        src=src,
        palette=palette,
        disk=disk,
        notify_ok=notify_ok,
        notify_msg=notify_msg,
        restarted_plasma=restarted,
        restart_msg=restart_msg,
    )
