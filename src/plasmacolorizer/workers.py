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
  4. write the ``.colors`` file under ``~/.local/share/color-schemes``,
  5. write color sections into ``~/.config/kdeglobals``.
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
from plasmacolorizer.core.palette import MaterialPalette


@dataclass
class WorkerResult:
    src: str
    palette: MaterialPalette
    scheme_path: Path
    kdeglobals_path: Path | None
    apply_ok: bool
    apply_error: str = ""


class GenerateSchemeWorker(QObject):
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
    ) -> None:
        super().__init__()
        self._src_path = src_path
        self._green = green_strength
        self._dark = dark
        self._quality = quality
        self._log = get_logger()

    # ------------------------------------------------------------------ utils

    def _emit(self, msg: str) -> None:
        # Log only on the GUI thread via progress -> MainWindow._append_log to
        # avoid duplicate file lines (same message from two thread IDs).
        self.progress.emit(msg)

    # ----------------------------------------------------------------- run()

    def run(self) -> None:
        log = self._log
        log.info("Worker.run() started")
        try:
            src = self._src_path
            if not Path(src).is_file():
                raise FileNotFoundError(
                    f"Wallpaper image not found: {src}"
                )
            self._emit(f"Source image: {src}")

            self._emit(f"Quantizing image (quality={self._quality})...")
            seed = pal.seed_color_from_image(src, quality=self._quality)
            log.debug("seed argb = 0x%08x", seed)

            if self._green > 0:
                self._emit(f"Applying green accent bias ({self._green * 100:.0f}%)...")
                seed = pal.apply_green_bias(seed, self._green)
                log.debug("seed after green bias = 0x%08x", seed)

            if self._dark is None:
                dark = kde_prefs.is_plasma_dark_scheme_preferred()
                self._emit(f"Dark mode (follow KDE): {dark}")
            else:
                dark = bool(self._dark)
                self._emit(f"Dark mode (forced): {dark}")

            self._emit("Building Material You palette...")
            mpl = pal.build_palette(seed, dark=dark)

            self._emit("Writing Plasma .colors file...")
            body = plasma_scheme.render_colors_file(mpl)
            written = plasma_scheme.write_scheme_file(body)
            self._emit(f"Scheme written: {written}")

            self._emit("Updating ~/.config/kdeglobals...")
            apply_ok = True
            apply_error = ""
            kdg_path: Path | None = None
            try:
                kdg_path = plasma_scheme.apply_to_kdeglobals(mpl)
                self._emit(f"kdeglobals updated: {kdg_path}")
            except Exception as exc:  # noqa: BLE001
                apply_ok = False
                apply_error = f"kdeglobals write failed: {exc}"
                log.exception("kdeglobals write failed")
                self._emit(apply_error)

            self._emit("Worker finished")
            self.finished.emit(WorkerResult(
                src=src,
                palette=mpl,
                scheme_path=written,
                kdeglobals_path=kdg_path,
                apply_ok=apply_ok,
                apply_error=apply_error,
            ))

        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            log.exception("Worker raised")
            tb = traceback.format_exc(limit=4)
            self.failed.emit(f"{exc}\n\n{tb}")
