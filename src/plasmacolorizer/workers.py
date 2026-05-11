"""Background workers for CPU-heavy image / palette tasks.

This module deliberately avoids touching DBus.  ``dbus-python`` does not
behave well when called from arbitrary Python threads (it can deadlock
indefinitely on the session bus), so all DBus calls are performed on the
main thread by ``ui.main_window`` either before the worker starts (to
resolve the wallpaper) or after it finishes (to notify running apps).

Only deterministic, thread-safe work runs here:

  1. quantize the wallpaper image into a seed color (materialyoucolor),
  2. apply the optional green accent bias,
  3. build a full Material You palette,
  4. optionally write the ``.colors`` file, ``kdeglobals``, and desktop theme
     (see ``plasma_scheme.apply_material_palette_to_disk``).
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from plasmacolorizer.core import kde_prefs
from plasmacolorizer.core import palette as pal
from plasmacolorizer.core import plasma_scheme
from plasmacolorizer.core.logger import get_logger
from plasmacolorizer.core.palette import MaterialPalette, merge_palette_color_overrides
from plasmacolorizer.core.plasma_scheme import SchemeApplyChoices


@dataclass
class WorkerResult:
    src: str
    palette: MaterialPalette
    scheme_path: Path
    kdeglobals_path: Path | None
    apply_ok: bool
    apply_error: str = ""
    choices: SchemeApplyChoices | None = None


def compute_material_palette_from_wallpaper(
    *,
    src_path: str,
    green_strength: float,
    dark: bool | None,
    quality: int,
    log=None,
) -> MaterialPalette:
    """Quantize image, optional green bias, build Material You palette (no disk writes)."""
    log = log or get_logger()
    src = src_path
    if not Path(src).is_file():
        raise FileNotFoundError(f"Wallpaper image not found: {src}")

    log.debug("quantize %s", src)
    seed = pal.seed_color_from_image(src, quality=quality)
    log.debug("seed argb = 0x%08x", seed)

    if green_strength > 0:
        seed = pal.apply_green_bias(seed, green_strength)
        log.debug("seed after green bias = 0x%08x", seed)

    if dark is None:
        dark = kde_prefs.is_plasma_dark_scheme_preferred()
    else:
        dark = bool(dark)

    return pal.build_palette(seed, dark=dark)


class PreviewPaletteWorker(QObject):
    """CPU-only path: wallpaper → MaterialPalette (no scheme files)."""

    finished = pyqtSignal(object)  # MaterialPalette
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        *,
        src_path: str,
        green_strength: float,
        dark: bool | None,
        quality: int,
    ) -> None:
        super().__init__()
        self._src_path = src_path
        self._green = green_strength
        self._dark = dark
        self._quality = quality
        self._log = get_logger()

    def _emit(self, msg: str) -> None:
        self.progress.emit(msg)

    def run(self) -> None:
        log = self._log
        log.info("PreviewPaletteWorker.run() started")
        try:
            self._emit(f"Source image: {self._src_path}")
            self._emit(f"Quantizing image (quality={self._quality})...")
            if self._green > 0:
                self._emit(f"Applying green accent bias ({self._green * 100:.0f}%)...")
            if self._dark is None:
                self._emit("Resolving dark/light from KDE preferences…")
            else:
                self._emit(f"Dark mode (forced): {bool(self._dark)}")
            self._emit("Building Material You palette…")
            mpl = compute_material_palette_from_wallpaper(
                src_path=self._src_path,
                green_strength=self._green,
                dark=self._dark,
                quality=self._quality,
                log=log,
            )
            self._emit("Preview palette ready (not yet written to disk).")
            self.finished.emit(mpl)
        except Exception as exc:  # noqa: BLE001
            log.exception("PreviewPaletteWorker raised")
            tb = traceback.format_exc(limit=4)
            self.failed.emit(f"{exc}\n\n{tb}")


class ApplyPaletteWorker(QObject):
    """Write an existing MaterialPalette to scheme files + kdeglobals + desktop theme."""

    finished = pyqtSignal(object)  # WorkerResult
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        *,
        src_path: str,
        palette: MaterialPalette,
        choices: SchemeApplyChoices | None,
    ) -> None:
        super().__init__()
        self._src = src_path
        self._palette = palette
        self._choices = choices
        self._log = get_logger()

    def _emit(self, msg: str) -> None:
        self.progress.emit(msg)

    def run(self) -> None:
        log = self._log
        log.info("ApplyPaletteWorker.run() started")
        try:
            self._emit("Writing Plasma .colors file and kdeglobals…")
            disk = plasma_scheme.apply_material_palette_to_disk(self._palette, self._choices)
            if not disk.apply_ok:
                self._emit(f"kdeglobals write failed: {disk.apply_error}")
                self.finished.emit(WorkerResult(
                    src=self._src,
                    palette=self._palette,
                    scheme_path=disk.scheme_path,
                    kdeglobals_path=None,
                    apply_ok=False,
                    apply_error=disk.apply_error,
                    choices=self._choices,
                ))
                return
            self._emit(f"Scheme written: {disk.scheme_path}")
            self._emit(f"kdeglobals updated: {disk.kdeglobals_path}")
            if disk.desktop_theme_path:
                self._emit(f"Desktop theme: {disk.desktop_theme_path}")
            if disk.desktop_theme_error:
                self._emit(
                    f"Desktop theme / plasmarc step failed (Qt apps still updated): "
                    f"{disk.desktop_theme_error}"
                )
            self._emit("Apply finished.")
            self.finished.emit(WorkerResult(
                src=self._src,
                palette=self._palette,
                scheme_path=disk.scheme_path,
                kdeglobals_path=disk.kdeglobals_path,
                apply_ok=True,
                apply_error="",
                choices=self._choices,
            ))
        except Exception as exc:  # noqa: BLE001
            log.exception("ApplyPaletteWorker raised")
            tb = traceback.format_exc(limit=4)
            self.failed.emit(f"{exc}\n\n{tb}")


class GenerateSchemeWorker(QObject):
    """One-shot: build palette from wallpaper and apply to disk (same as Preview + Apply)."""

    finished = pyqtSignal(object)  # WorkerResult
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        *,
        src_path: str,
        green_strength: float,
        dark: bool | None,
        quality: int,
        choices: SchemeApplyChoices | None = None,
        swatch_overrides: dict[str, tuple[int, int, int]] | None = None,
    ) -> None:
        super().__init__()
        self._src_path = src_path
        self._green = green_strength
        self._dark = dark
        self._quality = quality
        self._choices = choices
        self._swatch_overrides = dict(swatch_overrides) if swatch_overrides else {}
        self._log = get_logger()

    def _emit(self, msg: str) -> None:
        self.progress.emit(msg)

    def run(self) -> None:
        log = self._log
        log.info("GenerateSchemeWorker.run() started")
        try:
            self._emit(f"Source image: {self._src_path}")
            self._emit(f"Quantizing image (quality={self._quality})...")
            if self._green > 0:
                self._emit(f"Applying green accent bias ({self._green * 100:.0f}%)...")
            if self._dark is None:
                dark = kde_prefs.is_plasma_dark_scheme_preferred()
                self._emit(f"Dark mode (follow KDE): {dark}")
            else:
                dark = bool(self._dark)
                self._emit(f"Dark mode (forced): {dark}")

            self._emit("Building Material You palette...")
            mpl = compute_material_palette_from_wallpaper(
                src_path=self._src_path,
                green_strength=self._green,
                dark=self._dark,
                quality=self._quality,
                log=log,
            )
            if self._swatch_overrides:
                mpl = merge_palette_color_overrides(mpl, self._swatch_overrides)
                self._emit("Applied manual swatch overrides before writing scheme.")

            self._emit("Writing Plasma .colors file and kdeglobals…")
            disk = plasma_scheme.apply_material_palette_to_disk(mpl, self._choices)
            if not disk.apply_ok:
                self._emit(disk.apply_error)
                self.finished.emit(WorkerResult(
                    src=self._src_path,
                    palette=mpl,
                    scheme_path=disk.scheme_path,
                    kdeglobals_path=None,
                    apply_ok=False,
                    apply_error=disk.apply_error,
                    choices=self._choices,
                ))
                return

            self._emit(f"Scheme written: {disk.scheme_path}")
            self._emit(f"kdeglobals updated: {disk.kdeglobals_path}")
            if disk.desktop_theme_path:
                self._emit(f"Desktop theme: {disk.desktop_theme_path}")
            if disk.desktop_theme_error:
                self._emit(
                    f"Desktop theme / plasmarc step failed (Qt apps still updated): "
                    f"{disk.desktop_theme_error}"
                )
            self._emit("Worker finished")
            self.finished.emit(WorkerResult(
                src=self._src_path,
                palette=mpl,
                scheme_path=disk.scheme_path,
                kdeglobals_path=disk.kdeglobals_path,
                apply_ok=True,
                apply_error="",
                choices=self._choices,
            ))

        except Exception as exc:  # noqa: BLE001
            log.exception("GenerateSchemeWorker raised")
            tb = traceback.format_exc(limit=4)
            self.failed.emit(f"{exc}\n\n{tb}")
