"""Primary window with Colorizer and Conky tabs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QSize, Qt, QThread
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from plasmacolorizer.conky.templating import context_from_palette, render_template
from plasmacolorizer.core import plasma_scheme
from plasmacolorizer.core import wallpaper as wp
from plasmacolorizer.core.logger import get_logger, log_file_path
from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex
from plasmacolorizer.core.plasma_scheme import SchemeApplyChoices
from plasmacolorizer.workers import (
    ApplyPaletteWorker,
    GenerateSchemeWorker,
    PreviewPaletteWorker,
    WorkerResult,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PlasmaColorizer")
        self.resize(QSize(900, 640))

        self._log_file = log_file_path()
        self._logger = get_logger()
        self._logger.info("MainWindow started; log file: %s", self._log_file)

        self._last_palette: MaterialPalette | None = None
        self._last_wallpaper_src: str = ""
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._busy: QProgressDialog | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_color_tab(), "Colorizer")
        tabs.addTab(self._build_conky_tab(), "Conky")
        self.setCentralWidget(tabs)

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
        self._swatches: list[QLabel] = []
        for _name in ("primary", "secondary", "tertiary", "surface", "onSurface"):
            lab = QLabel()
            lab.setMinimumSize(44, 28)
            lab.setMaximumHeight(32)
            lab.setToolTip(_name)
            self._swatches.append(lab)
            sw_row.addWidget(lab)
        sw_row.addStretch(1)
        scheme_layout.addLayout(sw_row)

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
            "<b>Detect</b> reads the wallpaper path. <b>Preview palette</b> builds Material You colors "
            "from the image (CPU only). Adjust accent / emphasis / links, then "
            "<b>Apply scheme to Plasma</b> to write files and refresh KDE — or use "
            "<b>Generate and apply</b> for one step with the current mapping."
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
            "  - Detect: read wallpaper path. Preview palette: build Material You colors (no disk writes).\n"
            "  - Adjust accent / emphasis / links, then Apply scheme to Plasma — or Generate and apply in one step.\n"
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

    def _clear_swatches(self) -> None:
        for lab in self._swatches:
            lab.setToolTip("")
            lab.setStyleSheet(
                "QLabel { background: #2a2a32; border: 1px solid #444; border-radius: 4px; }"
            )

    def _update_palette_swatches(self, pal: MaterialPalette) -> None:
        keys = ("primary", "secondary", "tertiary", "surface", "onSurface")
        for key, lab in zip(keys, self._swatches, strict=True):
            rgb = pal.colors.get(key, (40, 40, 48))
            hx = rgb_to_hex(rgb)
            lab.setToolTip(f"{key}  {hx}")
            lab.setStyleSheet(
                f"QLabel {{ background-color: {hx}; border: 1px solid #555; border-radius: 4px; }}"
            )

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

    def _resolve_wallpaper_path(self) -> str | None:
        """Resolve the image path on the main thread (DBus must not run on worker thread)."""
        manual = self._manual_path.text().strip()
        if manual:
            if not Path(manual).is_file():
                QMessageBox.warning(self, "Wallpaper", f"Override path not found: {manual}")
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

    def _on_preview_palette(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._append_log("Already running.")
            return
        src = self._resolve_wallpaper_path()
        if src is None:
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

    def _on_preview_worker_finished(self, mpl_obj: object) -> None:
        pal = mpl_obj
        if not isinstance(pal, MaterialPalette):
            self._append_log("Preview finished with unexpected payload.")
            return
        self._last_palette = pal
        self._update_palette_swatches(pal)
        pri = pal.colors.get("primary", (0, 0, 0))
        self._append_log(
            f"Preview ready: primary={rgb_to_hex(pri)}, dark={pal.is_dark}. "
            "Adjust accent / emphasis / links above, then Apply scheme to Plasma."
        )

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

        thread = QThread(self)
        worker = ApplyPaletteWorker(
            src_path=src,
            palette=self._last_palette,
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
        self._path_display.setText(str(result.src))
        self._update_palette_swatches(result.palette)
        pri = result.palette.colors.get("primary", (0, 0, 0))
        self._append_log(f"Palette ready: primary={rgb_to_hex(pri)}, dark={result.palette.is_dark}")

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

        hint = QLabel(
            "Use <code>{{token}}</code> placeholders (e.g. <code>{{primary}}</code>, "
            "<code>{{on_surface}}</code>, <code>{{surface}}</code>). "
            "Tokens are filled from the last successful palette run on the Colorizer tab."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(hint)

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
        root.addLayout(grid)

        btn_row = QHBoxLayout()
        preview_btn = QPushButton("Preview render")
        preview_btn.clicked.connect(self._conky_preview)
        save_btn = QPushButton("Save rendered")
        save_btn.clicked.connect(self._conky_save)
        btn_row.addWidget(preview_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        preview_box = QGroupBox("Preview")
        pv_layout = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._conky_preview = QTextEdit()
        self._conky_preview.setReadOnly(True)
        self._conky_preview.setMinimumHeight(260)
        scroll.setWidget(self._conky_preview)
        pv_layout.addWidget(scroll)
        preview_box.setLayout(pv_layout)
        root.addWidget(preview_box)
        return wrap

    def _require_palette(self) -> MaterialPalette | None:
        if self._last_palette is None:
            QMessageBox.information(
                self,
                "Conky",
                "Generate a palette on the Colorizer tab first.",
            )
            return None
        return self._last_palette

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
        ctx = context_from_palette(pal)
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
        ctx = context_from_palette(pal)
        rendered = render_template(text, ctx)
        out.write_text(rendered, encoding="utf-8")
        QMessageBox.information(self, "Conky", f"Wrote {out}")
