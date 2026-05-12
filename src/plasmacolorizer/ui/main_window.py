"""Primary window with Colorizer and Conky tabs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QSize, Qt, QThread, QTimer
from PyQt6.QtGui import QColor, QCloseEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from plasmacolorizer.conky import presets as conky_presets
from plasmacolorizer.conky.fetch import GeocodeHit
from plasmacolorizer.conky.weather_locations import WEATHER_PRESETS
from plasmacolorizer.conky.settings_store import ConkySettings, load_conky_settings, save_conky_settings
from plasmacolorizer.conky.templating import render_template
from plasmacolorizer.core import plasma_scheme
from plasmacolorizer.core import wallpaper as wp
from plasmacolorizer.core.logger import get_logger, log_file_path
from plasmacolorizer.core.palette import MaterialPalette, merge_palette_color_overrides, rgb_to_hex
from plasmacolorizer.core.plasma_scheme import SchemeApplyChoices
from plasmacolorizer.workers import (
    ApplyPaletteWorker,
    GeocodeSearchWorker,
    GenerateSchemeWorker,
    PreviewPaletteWorker,
    WorkerResult,
)


_SWATCH_KEYS = ("primary", "secondary", "tertiary", "surface", "onSurface")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PlasmaColorizer")
        self.resize(QSize(900, 640))

        self._log_file = log_file_path()
        self._logger = get_logger()
        self._logger.info("MainWindow started; log file: %s", self._log_file)

        self._last_palette: MaterialPalette | None = None
        self._swatch_overrides: dict[str, tuple[int, int, int]] = {}
        self._last_wallpaper_src: str = ""
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._busy: QProgressDialog | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_color_tab(), "Colorizer")
        tabs.addTab(self._build_conky_tab(), "Conky")
        self.setCentralWidget(tabs)
        QTimer.singleShot(0, self._startup_autodetect_preview)

    # --- Colorizer tab -------------------------------------------------
    def _build_color_tab(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setSpacing(14)

        box = QGroupBox("Wallpaper and extraction")
        form = QFormLayout()
        self._path_display = QLineEdit()
        self._path_display.setReadOnly(True)
        self._path_display.setPlaceholderText("Detected wallpaper path appears here")

        self._manual_path = QLineEdit()
        self._manual_path.setPlaceholderText("Optional: explicit image path override")

        path_row = QHBoxLayout()
        path_row.addWidget(self._path_display, 1)
        btn_detect = QPushButton("Detect")
        btn_detect.setObjectName("secondary")
        btn_detect.clicked.connect(self._on_detect_wallpaper)
        path_row.addWidget(btn_detect)
        form.addRow("Current", path_row)
        form.addRow("Override", self._manual_path)

        self._monitor = QSpinBox()
        self._monitor.setRange(0, 16)
        self._monitor.setValue(0)

        self._quality = QSpinBox()
        self._quality.setRange(1, 10)
        self._quality.setValue(4)
        self._quality.setToolTip("Quantizer quality: higher = more sampling work")

        self._dark_combo = QComboBox()
        self._dark_combo.addItems(["Follow KDE", "Force dark", "Force light"])

        green_row = QHBoxLayout()
        self._green_slider = QSlider(Qt.Orientation.Horizontal)
        self._green_slider.setRange(0, 100)
        self._green_slider.setValue(0)
        self._green_label = QLabel("0%")
        self._green_slider.valueChanged.connect(lambda v: self._green_label.setText(f"{v}%"))
        green_row.addWidget(self._green_slider, 1)
        green_row.addWidget(self._green_label)

        form.addRow("Screen index", self._monitor)
        form.addRow("Quantizer quality", self._quality)
        form.addRow("UI mode", self._dark_combo)
        form.addRow("Green accent bias", green_row)

        box.setLayout(form)
        layout.addWidget(box)

        scheme_box = QGroupBox("Generated palette & scheme mapping")
        scheme_layout = QVBoxLayout()
        scheme_layout.setSpacing(10)

        sw_row = QHBoxLayout()
        sw_row.addWidget(QLabel("Swatches:"))
        self._swatch_buttons: list[QToolButton] = []
        for key in _SWATCH_KEYS:
            btn = QToolButton()
            btn.setMinimumSize(48, 30)
            btn.setMaximumHeight(34)
            btn.setAutoRaise(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(
                f"{key} — click to open the color dialog. "
                "On Plasma, the system picker often includes a screen color dropper. "
                "Right-click to reset this swatch."
            )
            btn.clicked.connect(lambda checked=False, k=key: self._edit_swatch_color(k))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, k=key, b=btn: self._on_swatch_context_menu(k, b.mapToGlobal(pos))
            )
            self._swatch_buttons.append(btn)
            sw_row.addWidget(btn)
        reset_sw = QPushButton("Reset swatches")
        reset_sw.setObjectName("secondary")
        reset_sw.setToolTip("Clear all manual swatch colors (back to generated preview).")
        reset_sw.clicked.connect(self._on_reset_swatches)
        sw_row.addWidget(reset_sw)
        sw_row.addStretch(1)
        scheme_layout.addLayout(sw_row)
        sw_hint = QLabel(
            "Click a swatch to choose a color (native dialog; KDE often provides a dropper). "
            "Overrides apply when you use Apply or Generate."
        )
        sw_hint.setWordWrap(True)
        scheme_layout.addWidget(sw_hint)

        map_form = QFormLayout()
        self._accent_combo = QComboBox()
        for label, key in (
            ("Primary (default)", "primary"),
            ("Secondary", "secondary"),
            ("Tertiary", "tertiary"),
            ("Primary fixed", "primaryFixed"),
        ):
            self._accent_combo.addItem(label, key)
        self._accent_combo.setToolTip(
            "Which Material color becomes the global Plasma accent and replaces "
            "the usual primary / primaryDim / onPrimary roles in the scheme."
        )

        self._emphasis_combo = QComboBox()
        for label, key in (
            ("Secondary (default)", "secondary"),
            ("Tertiary", "tertiary"),
            ("Primary", "primary"),
        ):
            self._emphasis_combo.addItem(label, key)
        self._emphasis_combo.setToolTip(
            "Replaces neutral / positive foreground tokens that normally use secondary."
        )

        self._links_combo = QComboBox()
        self._links_combo.addItem("Default (link + visited differ)", None)
        for label, key in (
            ("Tertiary", "tertiary"),
            ("Primary", "primary"),
            ("Secondary", "secondary"),
            ("Primary fixed", "primaryFixed"),
        ):
            self._links_combo.addItem(f"Unify links: {label}", key)
        self._links_combo.setToolTip(
            "Default keeps KDE view link colors as in the built-in mapping. "
            "Unify sets both visited and link text to the chosen Material color."
        )

        map_form.addRow("Plasma / KDE accent", self._accent_combo)
        map_form.addRow("Neutral emphasis", self._emphasis_combo)
        map_form.addRow("Application links", self._links_combo)
        scheme_layout.addLayout(map_form)

        scheme_box.setLayout(scheme_layout)
        layout.addWidget(scheme_box)

        step_hint = QLabel(
            "On launch the app <b>autodetects</b> the Plasma wallpaper for the chosen screen and "
            "<b>previews</b> the palette. Use <b>Detect</b> / <b>Override</b> / <b>Preview palette</b> "
            "any time to change the image. <b>Apply scheme to Plasma</b> writes files and refreshes KDE — "
            "or use <b>Generate and apply</b> for one step with the current mapping."
        )
        step_hint.setWordWrap(True)
        step_hint.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(step_hint)

        actions = QHBoxLayout()
        self._preview_btn = QPushButton("Preview palette")
        self._preview_btn.setObjectName("secondary")
        self._preview_btn.setToolTip(
            "Quantize the wallpaper and build a Material You palette. "
            "Does not write ~/.config or restart Plasma until you apply."
        )
        self._preview_btn.clicked.connect(self._on_preview_palette)

        self._apply_plasma_btn = QPushButton("Apply scheme to Plasma")
        self._apply_plasma_btn.setObjectName("secondary")
        self._apply_plasma_btn.setEnabled(False)
        self._apply_plasma_btn.setToolTip(
            "Writes the color scheme using the last previewed palette and the "
            "accent / emphasis / link choices above, then runs the same refresh as Generate."
        )
        self._apply_plasma_btn.clicked.connect(self._on_apply_scheme_only)

        self._apply_btn = QPushButton("Generate and apply scheme")
        self._apply_btn.setToolTip(
            "Quantizes the image, runs Material You, writes ~/.local/share/color-schemes/PlasmaColorizer.colors, "
            "merges colors into ~/.config/kdeglobals, then refreshes KWin / PlasmaShell / global accent."
        )
        self._apply_btn.clicked.connect(self._on_generate)

        clear_manual = QPushButton("Clear override")
        clear_manual.setObjectName("secondary")
        clear_manual.clicked.connect(self._manual_path.clear)
        actions.addWidget(self._preview_btn)
        actions.addWidget(self._apply_plasma_btn)
        actions.addWidget(self._apply_btn)
        actions.addWidget(clear_manual)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._restart_plasma = QCheckBox(
            "Restart Plasma shell afterward (required once after first apply; brief flicker)"
        )
        self._restart_plasma.setChecked(True)
        self._restart_plasma.setToolTip(
            "Plasma panel and Kickoff read colours from the active Plasma **desktop theme** "
            "(see ~/.local/share/plasma/desktoptheme/). After generating a theme, "
            "kquitapp6 plasmashell + kstart plasmashell reloads that cache. "
            "Leave this checked unless you know you do not need a full shell restart."
        )
        layout.addWidget(self._restart_plasma)

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout()
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        log_layout.addWidget(self._log)
        log_box.setLayout(log_layout)
        layout.addWidget(log_box)

        self._append_log(
            "Ready.\n"
            "  - Autodetect + preview runs once when the window opens (Plasma wallpaper for the screen index).\n"
            "  - Detect / Override / Preview palette: change the image any time (no disk writes until you apply).\n"
            "  - Click swatches to pick colors (KDE’s dialog often includes a screen dropper).\n"
            "  - Adjust accent / emphasis / links, then Apply — or Generate and apply in one step.\n"
            f"  - A detailed log is written to {self._log_file}"
        )
        self._clear_swatches()
        return outer

    def _dark_choice(self) -> bool | None:
        idx = self._dark_combo.currentIndex()
        return None if idx == 0 else (True if idx == 1 else False)

    def _scheme_choices(self) -> SchemeApplyChoices:
        ac = self._accent_combo.currentData()
        em = self._emphasis_combo.currentData()
        li = self._links_combo.currentData()
        return SchemeApplyChoices(
            accent=str(ac) if ac is not None else "primary",
            emphasis=str(em) if em is not None else "secondary",
            links=li if isinstance(li, str) else None,
        )

    def _effective_palette(self) -> MaterialPalette | None:
        if self._last_palette is None:
            return None
        return merge_palette_color_overrides(self._last_palette, self._swatch_overrides)

    def _clear_swatches(self) -> None:
        self._swatch_overrides.clear()
        for btn in self._swatch_buttons:
            btn.setToolTip("")
            btn.setStyleSheet(
                "QToolButton { background: #2a2a32; border: 1px solid #444; border-radius: 6px; }"
            )

    def _update_palette_swatches(self, pal: MaterialPalette | None = None) -> None:
        base = pal if pal is not None else self._last_palette
        if base is None:
            self._clear_swatches()
            return
        eff = merge_palette_color_overrides(base, self._swatch_overrides)
        for key, btn in zip(_SWATCH_KEYS, self._swatch_buttons, strict=True):
            rgb = eff.colors.get(key, (40, 40, 48))
            hx = rgb_to_hex(rgb)
            border = "#c9a227" if key in self._swatch_overrides else "#555"
            btn.setToolTip(
                f"{key}  {hx}"
                + ("  (manual)" if key in self._swatch_overrides else "  — click to edit")
            )
            btn.setStyleSheet(
                f"QToolButton {{ background-color: {hx}; border: 2px solid {border}; "
                "border-radius: 6px; }}"
            )

    def _edit_swatch_color(self, key: str) -> None:
        eff = self._effective_palette()
        if eff is None:
            QMessageBox.information(
                self,
                "Swatches",
                "Preview a palette first, then you can adjust swatch colors.",
            )
            return
        r, g, b = eff.colors.get(key, (128, 128, 128))
        initial = QColor(r, g, b)
        chosen = QColorDialog.getColor(initial, self, f"Choose color — {key}")
        if not chosen.isValid():
            return
        self._swatch_overrides[key] = (chosen.red(), chosen.green(), chosen.blue())
        self._update_palette_swatches()
        self._append_log(f"Swatch override {key}={rgb_to_hex(self._swatch_overrides[key])}")

    def _on_swatch_context_menu(self, key: str, global_pos: QPoint) -> None:
        menu = QMenu(self)
        reset_one = menu.addAction(f"Reset “{key}” to generated")
        chosen = menu.exec(global_pos)
        if chosen is reset_one and key in self._swatch_overrides:
            del self._swatch_overrides[key]
            self._update_palette_swatches()
            self._append_log(f"Swatch {key} reset to generated palette.")

    def _on_reset_swatches(self) -> None:
        if not self._swatch_overrides:
            return
        self._swatch_overrides.clear()
        if self._last_palette is not None:
            self._update_palette_swatches(self._last_palette)
        else:
            self._clear_swatches()
        self._append_log("All swatch overrides cleared.")

    def _set_color_tab_busy(self, running: bool) -> None:
        self._preview_btn.setEnabled(not running)
        self._apply_btn.setEnabled(not running)
        if running:
            self._apply_plasma_btn.setEnabled(False)
        else:
            self._apply_plasma_btn.setEnabled(self._last_palette is not None)

    def _append_log(self, msg: str) -> None:
        self._log.append(msg)
        self._logger.info(msg)

    def _resolve_wallpaper_path(self, *, silent: bool = False) -> str | None:
        """Resolve the image path on the main thread (DBus must not run on worker thread)."""
        manual = self._manual_path.text().strip()
        if manual:
            if not Path(manual).is_file():
                msg = f"Override path not found: {manual}"
                if silent:
                    self._append_log(msg)
                else:
                    QMessageBox.warning(self, "Wallpaper", msg)
                return None
            self._last_wallpaper_src = manual
            return manual

        existing = self._path_display.text().strip()
        if existing and Path(existing).is_file():
            self._last_wallpaper_src = existing
            return existing

        try:
            p = wp.current_wallpaper_image_path(self._monitor.value())
            self._last_wallpaper_src = p
            return p
        except Exception as exc:  # noqa: BLE001
            if silent:
                self._append_log(
                    f"Could not autodetect wallpaper via Plasma DBus ({exc}). "
                    "Use Detect or set Override, then Preview palette."
                )
            else:
                QMessageBox.warning(
                    self,
                    "Wallpaper",
                    f"Could not detect wallpaper via Plasma DBus.\n\n{exc}\n\n"
                    "Set the Override field to an explicit image path and try again.",
                )
            return None

    def _on_detect_wallpaper(self) -> None:
        try:
            path = wp.current_wallpaper_image_path(self._monitor.value())
            self._path_display.setText(path)
            self._last_wallpaper_src = path
            self._append_log(f"Detected wallpaper file: {path}")
            self._append_log("Next: Preview palette (recommended) or Generate and apply in one step.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Wallpaper", str(exc))
            self._append_log(f"Detect failed: {exc}")

    def _startup_autodetect_preview(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        src = self._resolve_wallpaper_path(silent=True)
        if src is None:
            return
        self._path_display.setText(src)
        self._append_log(f"Startup: autodetected wallpaper ({src}).")
        self._start_preview_palette(src)

    def _start_preview_palette(self, src: str) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._append_log("Already running.")
            return
        self._path_display.setText(src)
        self._last_wallpaper_src = src
        self._set_color_tab_busy(True)
        self._append_log("Preview: quantizing and building Material You palette…")

        thread = QThread(self)
        worker = PreviewPaletteWorker(
            src_path=src,
            green_strength=self._green_slider.value() / 100.0,
            dark=self._dark_choice(),
            quality=self._quality.value(),
        )
        self._thread = thread
        self._worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._append_log, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._on_preview_worker_finished, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_worker_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

    def _on_preview_palette(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._append_log("Already running.")
            return
        src = self._resolve_wallpaper_path()
        if src is None:
            return
        self._start_preview_palette(src)

    def _on_preview_worker_finished(self, mpl_obj: object) -> None:
        pal = mpl_obj
        if not isinstance(pal, MaterialPalette):
            self._append_log("Preview finished with unexpected payload.")
            return
        self._swatch_overrides.clear()
        self._last_palette = pal
        self._update_palette_swatches(pal)
        pri = pal.colors.get("primary", (0, 0, 0))
        self._append_log(
            f"Preview ready: primary={rgb_to_hex(pri)}, dark={pal.is_dark}. "
            "Adjust accent / emphasis / links above, then Apply scheme to Plasma."
        )
        self._refresh_running_conkys()

    def _on_apply_scheme_only(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._append_log("Already running.")
            return
        if self._last_palette is None:
            QMessageBox.information(
                self,
                "PlasmaColorizer",
                "Preview a palette first (or use Generate and apply), then you can apply with custom mapping.",
            )
            return
        src = self._path_display.text().strip()
        if not src or not Path(src).is_file():
            src = self._last_wallpaper_src
        if not src or not Path(src).is_file():
            QMessageBox.warning(self, "PlasmaColorizer", "No wallpaper image path — use Detect or set Override.")
            return

        self._set_color_tab_busy(True)
        self._append_log("Applying palette to Plasma files (respecting mapping choices)…")

        busy = QProgressDialog(self)
        busy.setWindowTitle("PlasmaColorizer")
        busy.setLabelText("Writing color scheme and updating KDE configuration…")
        busy.setRange(0, 0)
        busy.setMinimumDuration(0)
        busy.setModal(False)
        busy.setCancelButton(None)
        busy.setMinimumWidth(440)
        busy.show()
        self._busy = busy

        assert self._last_palette is not None
        pal_apply = merge_palette_color_overrides(self._last_palette, self._swatch_overrides)

        thread = QThread(self)
        worker = ApplyPaletteWorker(
            src_path=src,
            palette=pal_apply,
            choices=self._scheme_choices(),
        )
        self._thread = thread
        self._worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._append_log, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._on_worker_finished, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_worker_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

    def _close_busy(self) -> None:
        if self._busy is not None:
            self._busy.close()
            self._busy.deleteLater()
            self._busy = None

    def _on_generate(self) -> None:
        if self._thread and self._thread.isRunning():
            self._append_log("Already running.")
            return

        src = self._resolve_wallpaper_path()
        if src is None:
            return
        self._path_display.setText(src)
        self._last_wallpaper_src = src

        self._set_color_tab_busy(True)
        self._append_log("Generating: quantize, build palette, write .colors, update kdeglobals.")

        busy = QProgressDialog(self)
        busy.setWindowTitle("PlasmaColorizer")
        busy.setLabelText(
            "Computing palette and applying to Plasma.\n"
            "This usually takes a few seconds; large wallpapers can take longer."
        )
        busy.setRange(0, 0)
        busy.setMinimumDuration(0)
        busy.setModal(False)  # non-modal: keep the log visible and responsive
        busy.setCancelButton(None)
        busy.setMinimumWidth(440)
        busy.show()
        self._busy = busy

        thread = QThread(self)  # parented -> stays alive with MainWindow
        worker = GenerateSchemeWorker(
            src_path=src,
            green_strength=self._green_slider.value() / 100.0,
            dark=self._dark_choice(),
            quality=self._quality.value(),
            choices=self._scheme_choices(),
            swatch_overrides=dict(self._swatch_overrides),
        )
        # CRITICAL: keep strong references to BOTH thread and worker. Without
        # self._worker, the local `worker` is garbage-collected the moment
        # _on_generate returns and thread.started fires a slot on a dead
        # PyObject -> the worker never runs and the QThread stays alive
        # forever, blocking app shutdown.
        self._thread = thread
        self._worker = worker

        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._append_log, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._on_worker_finished, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_worker_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)

        thread.start()

    def _on_thread_finished(self) -> None:
        self._set_color_tab_busy(False)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    def _on_worker_finished(self, payload: object) -> None:
        self._close_busy()
        result: WorkerResult = payload  # type: ignore[assignment]
        self._last_palette = result.palette
        self._swatch_overrides.clear()
        self._path_display.setText(str(result.src))
        self._update_palette_swatches(result.palette)
        pri = result.palette.colors.get("primary", (0, 0, 0))
        self._append_log(f"Palette ready: primary={rgb_to_hex(pri)}, dark={result.palette.is_dark}")
        self._refresh_running_conkys()

        if not result.apply_ok:
            self._append_log(f"Apply error: {result.apply_error}")
            QMessageBox.warning(
                self,
                "PlasmaColorizer",
                f"Scheme file was written to:\n{result.scheme_path}\n\n"
                f"But colors could not be written to ~/.config/kdeglobals:\n{result.apply_error}\n\n"
                "Open System Settings -> Appearance -> Colors and pick "
                f"\"{plasma_scheme.SCHEME_FILE_STEM}\" manually.",
            )
            return

        # kdeglobals write succeeded; push palette to KWin, shell, and global accent (main thread).
        self._append_log("DBus: KWin + PlasmaShell + plasmashell.accentColor…")
        notify_ok, notify_msg = plasma_scheme.notify_kde_palette_change(
            result.palette,
            timeout=2.0,
            choices=result.choices,
        )
        self._append_log(notify_msg)

        restarted = False
        if self._restart_plasma.isChecked():
            self._append_log("Restarting plasmashell (full panel / launcher reload)…")
            rs_ok, rs_msg = plasma_scheme.restart_plasmashell()
            self._append_log(rs_msg)
            restarted = rs_ok

        if notify_ok and restarted:
            QMessageBox.information(
                self,
                "PlasmaColorizer",
                "Color scheme applied, global accent updated, and Plasma shell was restarted.\n\n"
                "The task bar and launcher should now follow the new palette.",
            )
        elif notify_ok:
            QMessageBox.information(
                self,
                "PlasmaColorizer",
                "Color scheme applied and the global Plasma accent was updated.\n\n"
                "If the task bar or Kickoff still look unchanged, enable "
                "\"Restart Plasma shell afterward\" and run again (or run manually:\n"
                "  kquitapp6 plasmashell && kstart plasmashell\n).",
            )
        elif restarted:
            QMessageBox.information(
                self,
                "PlasmaColorizer",
                "Colors were saved to kdeglobals and plasmashell was restarted.\n\n"
                "Some DBus refresh steps failed; check the log for details.",
            )
        else:
            QMessageBox.information(
                self,
                "PlasmaColorizer",
                f"Colors saved to:\n{result.kdeglobals_path}\n\n"
                "DBus refresh and shell restart did not all succeed — see the log.\n\n"
                "You can try manually:\n"
                "  kquitapp6 plasmashell && kstart plasmashell",
            )

    def _on_worker_failed(self, message: str) -> None:
        self._close_busy()
        self._append_log(f"Error: {message}")
        QMessageBox.critical(self, "PlasmaColorizer", message)

    # ----------------------------------------------------------- shutdown

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        """Make sure background threads do not keep the process alive."""
        thread = self._thread
        if thread is not None and thread.isRunning():
            self._logger.info("closeEvent: stopping worker thread")
            thread.quit()
            if not thread.wait(3000):
                self._logger.warning("closeEvent: worker thread did not quit in 3s; terminating")
                thread.terminate()
                thread.wait(1000)
        self._logger.info("closeEvent: accepting close")
        super().closeEvent(event)

    # --- Conky tab -----------------------------------------------------
    def _build_conky_tab(self) -> QWidget:
        wrap = QWidget()
        root = QVBoxLayout(wrap)

        bin_path = conky_presets.conky_binary()
        if not bin_path:
            miss = QLabel(
                "<b>conky</b> was not found in <code>PATH</code>. Install the <code>conky</code> package "
                "to use bundled presets; custom template preview still works."
            )
            miss.setWordWrap(True)
            miss.setTextFormat(Qt.TextFormat.RichText)
            root.addWidget(miss)

        bundled = QGroupBox("Bundled Conky presets")
        bundled_layout = QVBoxLayout()

        settings_form = QFormLayout()
        self._conky_esv_key = QLineEdit()
        self._conky_esv_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._conky_esv_key.setPlaceholderText("Crossway API token (api.esv.org)")
        self._conky_weather_preset = QComboBox()
        self._conky_weather_preset.addItem("Custom — edit city or coordinates below", None)
        for hit in WEATHER_PRESETS:
            self._conky_weather_preset.addItem(hit.label, hit)
        self._conky_weather_preset.setMinimumWidth(320)
        self._conky_weather_preset.currentIndexChanged.connect(self._on_weather_preset_changed)

        self._conky_weather_search_btn = QPushButton("Search Open-Meteo…")
        self._conky_weather_search_btn.setObjectName("secondary")
        self._conky_weather_search_btn.setToolTip(
            "Search the same geocoding database Open-Meteo uses on their site."
        )
        self._conky_weather_search_btn.clicked.connect(self._on_weather_open_meteo_search_clicked)

        quick_row = QHBoxLayout()
        quick_row.addWidget(self._conky_weather_preset, 1)
        quick_row.addWidget(self._conky_weather_search_btn)

        self._conky_weather_city = QLineEdit()
        self._conky_weather_city.setPlaceholderText("City text for geocoding, or set coordinates")
        self._conky_weather_city.textChanged.connect(self._on_weather_location_manual_edit)
        self._conky_weather_latlon = QLineEdit()
        self._conky_weather_latlon.setPlaceholderText("Optional: lat, lon (used with city if both set)")
        self._conky_weather_latlon.textChanged.connect(self._on_weather_location_manual_edit)

        self._conky_weather_temp_unit = QComboBox()
        self._conky_weather_temp_unit.addItem("Celsius (°C)", False)
        self._conky_weather_temp_unit.addItem("Fahrenheit (°F)", True)
        self._conky_weather_temp_unit.setToolTip("Open-Meteo forecast temperature unit for the Weather preset.")

        self._conky_system_stats_style = QComboBox()
        self._conky_system_stats_style.addItem("Text — percentages only", "text")
        self._conky_system_stats_style.addItem("Bar — CPU & RAM bars", "bar")
        self._conky_system_stats_style.addItem("Graph — CPU & RAM history", "graph")
        self._conky_system_stats_style.setToolTip(
            'How the bundled "System" preset draws CPU and RAM. Save, then '
            '"Apply colors to running Conkys" or restart that preset.'
        )

        self._conky_panel_opacity = QSlider(Qt.Orientation.Horizontal)
        self._conky_panel_opacity.setRange(0, 100)
        self._conky_panel_opacity.setValue(75)
        self._conky_panel_opacity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._conky_panel_opacity.setTickInterval(25)
        self._conky_panel_opacity.setToolTip(
            "Blends the palette surface color toward a neutral desktop tone. "
            "Bundled presets use a solid (opaque) dock window so KDE does not apply "
            "blur-behind translucency that ghosts after other windows overlap."
        )
        self._conky_panel_opacity_label = QLabel("75%")
        self._conky_panel_opacity_label.setMinimumWidth(40)
        self._conky_panel_opacity.valueChanged.connect(
            lambda v: self._conky_panel_opacity_label.setText(f"{v}%")
        )
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._conky_panel_opacity, 1)
        opacity_row.addWidget(self._conky_panel_opacity_label)

        settings_form.addRow("ESV API key", self._conky_esv_key)
        settings_form.addRow("Weather quick pick", quick_row)
        settings_form.addRow("Weather city", self._conky_weather_city)
        settings_form.addRow("Weather lat, lon", self._conky_weather_latlon)
        settings_form.addRow("Weather temperature", self._conky_weather_temp_unit)
        settings_form.addRow('System preset: CPU / RAM', self._conky_system_stats_style)
        settings_form.addRow("Bundled panel opacity", opacity_row)
        bundled_layout.addLayout(settings_form)

        save_row = QHBoxLayout()
        save_cfg = QPushButton("Save Conky settings")
        save_cfg.setObjectName("secondary")
        save_cfg.clicked.connect(self._conky_save_settings_clicked)
        save_row.addWidget(save_cfg)
        save_row.addStretch(1)
        bundled_layout.addLayout(save_row)

        self._conky_status_labels = {}
        self._conky_position_combos: dict[str, QComboBox] = {}
        for pid, meta in conky_presets.PRESETS.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(meta.title), 1)
            pos_combo = QComboBox()
            pos_combo.setMinimumWidth(132)
            pos_combo.setToolTip(
                "Screen position (3×3 grid). Save Conky settings, then Apply colors or restart this preset."
            )
            for align_key, grid_label in conky_presets.CONKY_GRID_ALIGNMENTS:
                pos_combo.addItem(grid_label, userData=align_key)
            self._conky_position_combos[pid] = pos_combo
            row.addWidget(pos_combo)
            st = QLabel("—")
            st.setMinimumWidth(72)
            self._conky_status_labels[pid] = st
            row.addWidget(st)
            b_start = QPushButton("Start")
            b_start.setObjectName("secondary")
            b_start.clicked.connect(lambda _c=False, p=pid: self._conky_start_preset(p))
            b_stop = QPushButton("Stop")
            b_stop.setObjectName("secondary")
            b_stop.clicked.connect(lambda _c=False, p=pid: self._conky_stop_preset(p))
            row.addWidget(b_start)
            row.addWidget(b_stop)
            bundled_layout.addLayout(row)

        apply_row = QHBoxLayout()
        apply_colors = QPushButton("Apply colors to running Conkys")
        apply_colors.setToolTip(
            "Re-render bundled configs from the current palette and restart any preset that was running."
        )
        apply_colors.clicked.connect(self._conky_apply_colors_clicked)
        stop_all = QPushButton("Stop all presets")
        stop_all.setObjectName("secondary")
        stop_all.clicked.connect(self._conky_stop_all_clicked)
        apply_row.addWidget(apply_colors)
        apply_row.addWidget(stop_all)
        apply_row.addStretch(1)
        bundled_layout.addLayout(apply_row)

        bundled.setLayout(bundled_layout)
        root.addWidget(bundled)

        hint = QLabel(
            "Bundled presets use <code>{{token}}</code> colors from the Colorizer tab. "
            "Verse uses ESV (Crossway terms apply). Weather uses "
            "<a href=\"https://open-meteo.com\">Open-Meteo</a> "
            "(<a href=\"https://open-meteo.com/en/docs/geocoding-api\">geocoding</a> for search)."
        )
        hint.setWordWrap(True)
        hint.setOpenExternalLinks(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(hint)

        custom = QGroupBox("Custom template")
        custom_layout = QVBoxLayout()
        ch = QLabel(
            "Use <code>{{token}}</code> (e.g. <code>{{primary}}</code>, "
            "<code>{{on_surface}}</code>). Filled from the current effective palette."
        )
        ch.setWordWrap(True)
        ch.setTextFormat(Qt.TextFormat.RichText)
        custom_layout.addWidget(ch)

        grid = QFormLayout()
        self._conky_in = QLineEdit()
        self._conky_out = QLineEdit()
        browse_in = QPushButton("Browse…")
        browse_in.setObjectName("secondary")
        browse_in.clicked.connect(self._pick_conky_in)
        browse_out = QPushButton("Browse…")
        browse_out.setObjectName("secondary")
        browse_out.clicked.connect(self._pick_conky_out)

        in_row = QHBoxLayout()
        in_row.addWidget(self._conky_in, 1)
        in_row.addWidget(browse_in)
        out_row = QHBoxLayout()
        out_row.addWidget(self._conky_out, 1)
        out_row.addWidget(browse_out)

        grid.addRow("Template file", in_row)
        grid.addRow("Output file", out_row)
        custom_layout.addLayout(grid)

        btn_row = QHBoxLayout()
        preview_btn = QPushButton("Preview render")
        preview_btn.clicked.connect(self._conky_preview)
        save_btn = QPushButton("Save rendered")
        save_btn.clicked.connect(self._conky_save)
        btn_row.addWidget(preview_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch(1)
        custom_layout.addLayout(btn_row)

        custom.setLayout(custom_layout)
        root.addWidget(custom)

        preview_box = QGroupBox("Preview")
        pv_layout = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._conky_preview = QTextEdit()
        self._conky_preview.setReadOnly(True)
        self._conky_preview.setMinimumHeight(200)
        scroll.setWidget(self._conky_preview)
        pv_layout.addWidget(scroll)
        preview_box.setLayout(pv_layout)
        root.addWidget(preview_box)

        self._load_conky_settings_into_fields()
        self._refresh_conky_status_labels()
        return wrap

    def _parse_lat_lon_field(self, text: str) -> tuple[float | None, float | None]:
        t = text.strip()
        if not t:
            return None, None
        parts = [x.strip() for x in t.replace(",", " ").split() if x.strip()]
        if len(parts) != 2:
            return None, None
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return None, None

    def _set_weather_hit_fields(self, hit: GeocodeHit) -> None:
        self._conky_weather_city.blockSignals(True)
        self._conky_weather_latlon.blockSignals(True)
        try:
            self._conky_weather_city.setText(hit.label)
            self._conky_weather_latlon.setText(f"{hit.latitude}, {hit.longitude}")
        finally:
            self._conky_weather_city.blockSignals(False)
            self._conky_weather_latlon.blockSignals(False)

    def _on_weather_preset_changed(self, idx: int) -> None:
        if idx <= 0:
            return
        hit = self._conky_weather_preset.itemData(idx)
        if not isinstance(hit, GeocodeHit):
            return
        self._set_weather_hit_fields(hit)

    def _on_weather_location_manual_edit(self) -> None:
        self._conky_weather_preset.blockSignals(True)
        try:
            self._conky_weather_preset.setCurrentIndex(0)
        finally:
            self._conky_weather_preset.blockSignals(False)

    def _sync_weather_preset_combo(self) -> None:
        lat, lon = self._parse_lat_lon_field(self._conky_weather_latlon.text())
        idx = 0
        if lat is not None and lon is not None:
            tol = 0.025
            for i, hit in enumerate(WEATHER_PRESETS, start=1):
                if abs(hit.latitude - lat) < tol and abs(hit.longitude - lon) < tol:
                    idx = i
                    break
        self._conky_weather_preset.blockSignals(True)
        try:
            self._conky_weather_preset.setCurrentIndex(idx)
        finally:
            self._conky_weather_preset.blockSignals(False)

    def _on_weather_open_meteo_search_clicked(self) -> None:
        dlg = QDialog(self)
        dlg.setMinimumWidth(460)
        dlg.setWindowTitle("Search location — Open-Meteo")
        lay = QVBoxLayout(dlg)

        hint = QLabel(
            "Uses the public "
            '<a href="https://open-meteo.com/en/docs/geocoding-api">Open-Meteo geocoding API</a> '
            "(same place index as the website). Choose a row, then <b>Use selection</b>."
        )
        hint.setWordWrap(True)
        hint.setOpenExternalLinks(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(hint)

        entry = QLineEdit()
        entry.setPlaceholderText("e.g. Mannheim, 大阪, Cape Town…")
        btn_search = QPushButton("Search")
        btn_search.setObjectName("secondary")
        row = QHBoxLayout()
        row.addWidget(entry, 1)
        row.addWidget(btn_search)
        lay.addLayout(row)

        list_w = QListWidget()
        list_w.setMinimumHeight(240)
        lay.addWidget(list_w)

        def start_search() -> None:
            q = entry.text().strip()
            if not q:
                QMessageBox.information(dlg, "Search", "Enter a place name first.")
                return
            prev = getattr(dlg, "_geo_thread", None)
            if isinstance(prev, QThread) and prev.isRunning():
                return
            btn_search.setEnabled(False)
            list_w.clear()
            thread = QThread(dlg)
            worker = GeocodeSearchWorker(q)
            dlg._geo_thread = thread  # noqa: SLF001
            dlg._geo_worker = worker  # noqa: SLF001
            worker.moveToThread(thread)

            def on_fin(hits: object) -> None:
                btn_search.setEnabled(True)
                if not isinstance(hits, list):
                    hits = []
                for h in hits:
                    if not isinstance(h, GeocodeHit):
                        continue
                    it = QListWidgetItem(h.label)
                    it.setData(Qt.ItemDataRole.UserRole, h)
                    list_w.addItem(it)
                if not hits:
                    tip = QListWidgetItem("No results — try different words or enter lat/lon manually.")
                    tip.setFlags(tip.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    list_w.addItem(tip)
                thread.quit()

            def on_fail(msg: str) -> None:
                btn_search.setEnabled(True)
                QMessageBox.warning(dlg, "Geocoding", msg)
                thread.quit()

            thread.started.connect(worker.run)
            worker.finished.connect(on_fin)
            worker.failed.connect(on_fail)
            thread.finished.connect(worker.deleteLater)
            thread.start()

        def apply_selection() -> None:
            it = list_w.currentItem()
            if it is None:
                QMessageBox.information(dlg, "Use selection", "Choose a row in the list first.")
                return
            hit = it.data(Qt.ItemDataRole.UserRole)
            if not isinstance(hit, GeocodeHit):
                return
            self._set_weather_hit_fields(hit)
            self._conky_weather_preset.blockSignals(True)
            try:
                self._conky_weather_preset.setCurrentIndex(0)
            finally:
                self._conky_weather_preset.blockSignals(False)
            dlg.accept()

        btn_search.clicked.connect(start_search)
        entry.returnPressed.connect(start_search)
        list_w.itemDoubleClicked.connect(lambda _it: apply_selection())

        bb = QDialogButtonBox()
        bb.addButton("Use selection", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Close)
        bb.accepted.connect(apply_selection)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)

        dlg.exec()

    def _load_conky_settings_into_fields(self) -> None:
        s = load_conky_settings()
        self._conky_esv_key.setText(s.esv_api_key)
        self._conky_weather_city.blockSignals(True)
        self._conky_weather_latlon.blockSignals(True)
        try:
            self._conky_weather_city.setText(s.weather_city)
            if s.weather_lat is not None and s.weather_lon is not None:
                self._conky_weather_latlon.setText(f"{s.weather_lat}, {s.weather_lon}")
            else:
                self._conky_weather_latlon.clear()
        finally:
            self._conky_weather_city.blockSignals(False)
            self._conky_weather_latlon.blockSignals(False)
        self._sync_weather_preset_combo()
        self._conky_weather_temp_unit.setCurrentIndex(1 if s.weather_fahrenheit else 0)
        for i in range(self._conky_system_stats_style.count()):
            if self._conky_system_stats_style.itemData(i) == s.system_stats_style:
                self._conky_system_stats_style.setCurrentIndex(i)
                break
        pct = max(0, min(100, round(float(s.conky_panel_opacity) * 100)))
        self._conky_panel_opacity.blockSignals(True)
        self._conky_panel_opacity.setValue(pct)
        self._conky_panel_opacity.blockSignals(False)
        self._conky_panel_opacity_label.setText(f"{pct}%")
        self._sync_conky_position_combos_from_settings()

    def _sync_conky_position_combos_from_settings(self) -> None:
        s = load_conky_settings()
        valid = frozenset(a for a, _ in conky_presets.CONKY_GRID_ALIGNMENTS)
        for pid, combo in self._conky_position_combos.items():
            want = (s.conky_preset_positions.get(pid) or "").strip()
            if want not in valid:
                want = conky_presets.default_alignment_for_preset(pid)
            for i in range(combo.count()):
                if combo.itemData(i) == want:
                    combo.setCurrentIndex(i)
                    break

    def _conky_save_settings_clicked(self) -> None:
        lat, lon = self._parse_lat_lon_field(self._conky_weather_latlon.text())
        wf = self._conky_weather_temp_unit.currentData()
        style = self._conky_system_stats_style.currentData()
        settings = ConkySettings(
            esv_api_key=self._conky_esv_key.text().strip(),
            weather_city=self._conky_weather_city.text().strip(),
            weather_lat=lat,
            weather_lon=lon,
            weather_fahrenheit=bool(wf),
            system_stats_style=str(style or "text"),
            conky_panel_opacity=max(0.0, min(1.0, self._conky_panel_opacity.value() / 100.0)),
            conky_preset_positions={
                pid: str(
                    self._conky_position_combos[pid].currentData()
                    or conky_presets.default_alignment_for_preset(pid)
                )
                for pid in self._conky_position_combos
            },
        )
        path = save_conky_settings(settings)
        self._append_log(f"Conky settings saved to {path}")
        QMessageBox.information(self, "Conky", f"Settings saved to:\n{path}")

    def _refresh_conky_status_labels(self) -> None:
        for pid, lab in self._conky_status_labels.items():
            lab.setText("running" if conky_presets.is_preset_running(pid) else "stopped")

    def _conky_start_preset(self, preset_id: str) -> None:
        pal = self._require_palette()
        if pal is None:
            return
        ok, msg = conky_presets.start_preset(preset_id, pal)
        self._append_log(f"Conky [{preset_id}]: {msg}")
        if not ok:
            QMessageBox.warning(self, "Conky", msg)
        self._refresh_conky_status_labels()

    def _conky_stop_preset(self, preset_id: str) -> None:
        ok, msg = conky_presets.stop_preset(preset_id)
        self._append_log(f"Conky [{preset_id}]: {msg}")
        if not ok:
            QMessageBox.warning(self, "Conky", msg)
        self._refresh_conky_status_labels()

    def _conky_stop_all_clicked(self) -> None:
        conky_presets.stop_all_presets()
        self._append_log("Conky: stopped all bundled presets.")
        self._refresh_conky_status_labels()

    def _conky_apply_colors_clicked(self) -> None:
        pal = self._require_palette()
        if pal is None:
            return
        running = [p for p in conky_presets.PRESETS if conky_presets.is_preset_running(p)]
        if not running:
            QMessageBox.information(
                self,
                "Conky",
                "No bundled presets are running. Start one first, or use this after you have Conkys up.",
            )
            return
        for p in running:
            conky_presets.stop_preset(p)
        conky_presets.render_all_presets(pal)
        for p in running:
            ok, msg = conky_presets.start_preset(p, pal)
            self._append_log(f"Conky [{p}] refresh: {msg}")
            if not ok:
                QMessageBox.warning(self, "Conky", f"{p}: {msg}")
        self._refresh_conky_status_labels()

    def _refresh_running_conkys(self) -> None:
        pal = self._effective_palette()
        if pal is None:
            return
        running = [p for p in conky_presets.PRESETS if conky_presets.is_preset_running(p)]
        if not running:
            return
        for p in running:
            conky_presets.stop_preset(p)
        conky_presets.render_all_presets(pal)
        for p in running:
            ok, msg = conky_presets.start_preset(p, pal)
            self._append_log(f"Conky [{p}] palette refresh: {msg}")
        self._refresh_conky_status_labels()

    def _require_palette(self) -> MaterialPalette | None:
        pal = self._effective_palette()
        if pal is None:
            QMessageBox.information(
                self,
                "Conky",
                "Generate a palette on the Colorizer tab first.",
            )
            return None
        return pal

    def _pick_conky_in(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Conky template", str(Path.home()))
        if path:
            self._conky_in.setText(path)

    def _pick_conky_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Rendered Conky config", str(Path.home() / "conky.conf"))
        if path:
            self._conky_out.setText(path)

    def _read_template_file(self) -> str:
        p = Path(self._conky_in.text().strip())
        if not p.is_file():
            raise FileNotFoundError(f"Template not found: {p}")
        return p.read_text(encoding="utf-8", errors="replace")

    def _conky_preview(self) -> None:
        pal = self._require_palette()
        if pal is None:
            return
        try:
            text = self._read_template_file()
        except OSError as exc:
            QMessageBox.warning(self, "Conky", str(exc))
            return
        ctx = conky_presets.build_render_context(pal)
        self._conky_preview.setPlainText(render_template(text, ctx))

    def _conky_save(self) -> None:
        pal = self._require_palette()
        if pal is None:
            return
        out = Path(self._conky_out.text().strip())
        if not out.parent.is_dir():
            QMessageBox.warning(self, "Conky", f"Output directory missing: {out.parent}")
            return
        try:
            text = self._read_template_file()
        except OSError as exc:
            QMessageBox.warning(self, "Conky", str(exc))
            return
        ctx = conky_presets.build_render_context(pal)
        rendered = render_template(text, ctx)
        out.write_text(rendered, encoding="utf-8")
        QMessageBox.information(self, "Conky", f"Wrote {out}")
