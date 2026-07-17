"""Primary window with Colorizer, Conky, and Log tabs."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QSize, Qt, QThread, QTimer, QUrl
from PyQt6.QtGui import QColor, QCloseEvent, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from plasmacolorizer.conky import presets as conky_presets
from plasmacolorizer.conky import themes as conky_themes
from plasmacolorizer.conky.fetch import GeocodeHit
from plasmacolorizer.conky.weather_locations import WEATHER_PRESETS
from plasmacolorizer.conky.settings_store import (
    ConkyShortcut,
    ConkySettings,
    default_conky_shortcuts,
    load_conky_settings,
    save_conky_settings,
)
from plasmacolorizer.conky.templating import render_template
from plasmacolorizer.core import plasma_scheme
from plasmacolorizer.core import wallpaper as wp
from plasmacolorizer.core.app_settings import AppSettings, load_app_settings, save_app_settings
from plasmacolorizer.core.wallpaper_watch import (
    WALLPAPER_CHANGE_DEBOUNCE_MS,
    WALLPAPER_POLL_INTERVAL_MS,
    record_applied_wallpaper_fingerprint,
    wallpaper_fingerprint,
    wallpaper_fingerprint_for_path,
    wallpaper_watch_skipped,
)
from plasmacolorizer import wallpaper_daemon
from plasmacolorizer.core.component_colors import (
    COMPONENT_BY_ID,
    PLASMA_COMPONENTS,
    ComponentColorOverride,
    apply_component_color_overrides,
    component_tooltip,
    effective_component_rgb,
    overrides_from_settings_dict,
    overrides_to_settings_dict,
    resolve_override_rgb,
)
from plasmacolorizer.core.logger import get_logger, log_file_path
from plasmacolorizer.core.palette import MaterialPalette, merge_palette_color_overrides, rgb_to_hex
from plasmacolorizer.core.plasma_scheme import SchemeApplyChoices, str_to_panel_opacity_mode
from plasmacolorizer.core import terminals as terminal_backends
from plasmacolorizer.core.terminal_settings import (
    TerminalSettings,
    load_terminal_settings,
    parse_hex_rgb,
    save_terminal_settings,
)
from plasmacolorizer.ui.component_color_dialog import ComponentColorDialog
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
        self.resize(QSize(900, 520))

        self._log_file = log_file_path()
        self._logger = get_logger()
        self._logger.info("MainWindow started; log file: %s", self._log_file)

        self._last_palette: MaterialPalette | None = None
        self._swatch_overrides: dict[str, tuple[int, int, int]] = {}
        self._component_overrides: dict[str, ComponentColorOverride] = {}
        self._last_wallpaper_src: str = ""
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._busy: QProgressDialog | None = None
        self._last_wallpaper_fingerprint: str | None = None
        self._pending_wallpaper_path: str | None = None
        self._suppress_apply_dialogs = False

        # Timers must exist before building tabs: loading app settings toggles the
        # wallpaper-daemon checkbox, which used to call into these before init.
        self._wallpaper_debounce_timer = QTimer(self)
        self._wallpaper_debounce_timer.setSingleShot(True)
        self._wallpaper_debounce_timer.setInterval(WALLPAPER_CHANGE_DEBOUNCE_MS)
        self._wallpaper_debounce_timer.timeout.connect(self._on_wallpaper_change_debounced)

        self._wallpaper_poll_timer = QTimer(self)
        self._wallpaper_poll_timer.setInterval(WALLPAPER_POLL_INTERVAL_MS)
        self._wallpaper_poll_timer.timeout.connect(self._on_wallpaper_poll_tick)

        tabs = QTabWidget()
        log_tab = self._build_log_tab()
        color_tab = self._build_color_tab()
        terminal_tab = self._build_terminal_tab()
        conky_tab = self._build_conky_tab()
        tabs.addTab(color_tab, "Colorizer")
        tabs.addTab(terminal_tab, "Terminal")
        tabs.addTab(conky_tab, "Conky")
        tabs.addTab(log_tab, "Log")
        self.setCentralWidget(tabs)

        self._append_log(
            "Ready.\n"
            "  - Autodetect + preview runs once when the window opens (Plasma wallpaper for the screen index).\n"
            "  - Detect / Override / Preview palette: change the image any time (no disk writes until you apply).\n"
            "  - Click swatches to pick colors (KDE’s dialog often includes a screen dropper).\n"
            "  - Adjust accent / emphasis / links, then Apply — or Generate and apply in one step.\n"
            f"  - A detailed log is written to {self._log_file}"
        )
        if plasma_scheme.theme_plasmarc_has_breaking_sections():
            self._append_log(
                "WARN: PlasmaColorizer theme plasmarc contains opacity-breaking sections — "
                "panel Solid / Adaptive / Translucent may all look the same. "
                "Use Repair theme for panel opacity on the Colorizer tab."
            )
        self._update_panel_opacity_repair_btn()

        self._sync_wallpaper_watchers()
        self._update_daemon_status_label()

        QTimer.singleShot(0, self._startup_autodetect_preview)

    # --- Colorizer tab -------------------------------------------------
    def _build_color_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
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
        self._monitor.valueChanged.connect(self._save_app_settings_from_ui)

        self._quality = QSpinBox()
        self._quality.setRange(1, 10)
        self._quality.setValue(4)
        self._quality.setToolTip("Quantizer quality: higher = more sampling work")

        self._dark_combo = QComboBox()
        self._dark_combo.addItems(["Follow KDE", "Force dark", "Force light"])

        primary_bias_row = QHBoxLayout()
        self._primary_bias_slider = QSlider(Qt.Orientation.Horizontal)
        self._primary_bias_slider.setRange(0, 100)
        self._primary_bias_slider.setValue(0)
        self._primary_bias_slider.setToolTip(
            "Nudges the wallpaper seed toward the Material primary accent for the "
            "chosen light/dark mode. 0% = raw extracted colour, 100% = strongest "
            "primary emphasis (still wallpaper-driven, not a fixed hue)."
        )
        self._primary_bias_label = QLabel("0%")
        self._primary_bias_slider.valueChanged.connect(
            lambda v: self._primary_bias_label.setText(f"{v}%")
        )
        primary_bias_row.addWidget(self._primary_bias_slider, 1)
        primary_bias_row.addWidget(self._primary_bias_label)

        form.addRow("Screen index", self._monitor)
        form.addRow("Quantizer quality", self._quality)
        form.addRow("UI mode", self._dark_combo)
        form.addRow("Primary color bias", primary_bias_row)

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

        self._component_colors_toggle = QCheckBox("Show component color overrides (optional)")
        self._component_colors_toggle.setToolTip(
            "Pin specific KDE roles (panel, launcher, selection, etc.) to palette colours or "
            "a custom pick. Automated mapping still applies everywhere you do not override."
        )
        scheme_layout.addWidget(self._component_colors_toggle)

        self._component_colors_container = QWidget()
        comp_layout = QVBoxLayout(self._component_colors_container)
        comp_layout.setContentsMargins(0, 0, 0, 0)
        comp_hint = QLabel(
            "Click a swatch to pick from the generated palette or use a custom colour / screen dropper. "
            "Overrides persist across applies; Reset returns that role to automated mapping."
        )
        comp_hint.setWordWrap(True)
        comp_layout.addWidget(comp_hint)

        self._component_buttons: dict[str, QToolButton] = {}
        self._component_reset_buttons: dict[str, QPushButton] = {}
        comp_form = QFormLayout()
        for comp in PLASMA_COMPONENTS:
            row = QHBoxLayout()
            btn = QToolButton()
            btn.setMinimumSize(48, 28)
            btn.setAutoRaise(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, cid=comp.id: self._edit_component_color(cid))
            self._component_buttons[comp.id] = btn
            row.addWidget(btn)
            reset = QPushButton("Reset")
            reset.setObjectName("secondary")
            reset.setMaximumWidth(72)
            reset.setEnabled(False)
            reset.clicked.connect(lambda checked=False, cid=comp.id: self._reset_component_color(cid))
            self._component_reset_buttons[comp.id] = reset
            row.addWidget(reset)
            row.addStretch(1)
            comp_form.addRow(comp.label, row)
        comp_layout.addLayout(comp_form)

        reset_all_comp = QPushButton("Reset all component overrides")
        reset_all_comp.setObjectName("secondary")
        reset_all_comp.clicked.connect(self._reset_all_component_colors)
        comp_layout.addWidget(reset_all_comp)
        self._component_colors_container.setVisible(False)
        self._component_colors_toggle.toggled.connect(self._component_colors_container.setVisible)
        scheme_layout.addWidget(self._component_colors_container)

        self._plasma_strong_panel_tint = QCheckBox("Strong panel tint (primaryContainer backgrounds)")
        self._plasma_strong_panel_tint.setToolTip(
            "Tints the KDE taskbar / panel background toward the palette primary container colour "
            "so applied colours are more visible than the default neutral surface tones."
        )
        scheme_layout.addWidget(self._plasma_strong_panel_tint)

        self._plasma_panel_opacity_combo = QComboBox()
        for label, mode in (
            ("Solid (recommended)", "opaque"),
            ("Adaptive (opaque when window touches panel)", "adaptive"),
            ("Translucent (wallpaper shows through)", "translucent"),
        ):
            self._plasma_panel_opacity_combo.addItem(label, mode)
        self._plasma_panel_opacity_combo.setToolTip(
            "Plasma 6 panel opacity mode (not partial alpha like Conky). "
            "Solid keeps scheme colours visible on the taskbar. "
            "Translucent can make a dark panel look like it vanished. "
            "Changes are saved without restarting plasmashell (safe mode)."
        )
        self._plasma_panel_opacity_combo.currentIndexChanged.connect(
            self._on_plasma_panel_opacity_mode_changed,
        )
        opacity_form = QFormLayout()
        opacity_form.addRow("Panel opacity", self._plasma_panel_opacity_combo)
        scheme_layout.addLayout(opacity_form)

        opacity_diag_row = QHBoxLayout()
        self._panel_opacity_diagnose_btn = QPushButton("Diagnose panel opacity")
        self._panel_opacity_diagnose_btn.setObjectName("secondary")
        self._panel_opacity_diagnose_btn.setToolTip(
            "Run checks on plasmashellrc, live panel state, Plasma Style plasmarc, "
            "competing tools, and KWin blur."
        )
        self._panel_opacity_diagnose_btn.clicked.connect(self._on_diagnose_panel_opacity)
        self._panel_opacity_repair_btn = QPushButton("Repair theme for panel opacity")
        self._panel_opacity_repair_btn.setObjectName("secondary")
        self._panel_opacity_repair_btn.setToolTip(
            "Remove opacity-breaking sections from the PlasmaColorizer theme plasmarc. "
            "Does not restart plasmashell unless you ask it to."
        )
        self._panel_opacity_repair_btn.clicked.connect(self._on_repair_panel_opacity)
        opacity_diag_row.addWidget(self._panel_opacity_diagnose_btn)
        opacity_diag_row.addWidget(self._panel_opacity_repair_btn)
        opacity_diag_row.addStretch(1)
        scheme_layout.addLayout(opacity_diag_row)

        plasma_opacity_hint = QLabel(
            "Prefer <b>Solid</b>. Adaptive/Translucent can make a dark Material You panel "
            "look missing even though plasmashell is still running. "
            "Modes are saved to plasmashellrc without auto-restarting the shell."
        )
        plasma_opacity_hint.setWordWrap(True)
        plasma_opacity_hint.setTextFormat(Qt.TextFormat.RichText)
        scheme_layout.addWidget(plasma_opacity_hint)

        scheme_box.setLayout(scheme_layout)
        layout.addWidget(scheme_box)

        self._apply_konsole_scheme = QCheckBox("Apply palette to Konsole (default profile)")
        self._apply_konsole_scheme.setChecked(True)
        self._apply_konsole_scheme.setToolTip(
            "Writes ~/.local/share/konsole/PlasmaColorizer.colorscheme and updates the "
            "default profile from konsolerc when you apply a palette."
        )
        self._apply_konsole_scheme.toggled.connect(self._save_app_settings_from_ui)
        layout.addWidget(self._apply_konsole_scheme)

        self._dolphin_follow_system = QCheckBox("Point Dolphin at system color scheme")
        self._dolphin_follow_system.setChecked(True)
        self._dolphin_follow_system.setToolTip(
            "Sets ~/.config/dolphinrc [UiSettings] ColorScheme=* so Dolphin follows the "
            "global Plasma scheme instead of a per-app pin (e.g. MaterialYouDark)."
        )
        self._dolphin_follow_system.toggled.connect(self._save_app_settings_from_ui)
        layout.addWidget(self._dolphin_follow_system)

        self._auto_apply_wallpaper = QCheckBox("Automatically re-apply when wallpaper changes")
        self._auto_apply_wallpaper.setChecked(True)
        self._auto_apply_wallpaper.setToolTip(
            "While PlasmaColorizer is open, poll the Plasma wallpaper every 30s and run "
            "Generate and apply when it changes (skipped when Override is set)."
        )
        self._auto_apply_wallpaper.toggled.connect(self._save_app_settings_from_ui)
        layout.addWidget(self._auto_apply_wallpaper)

        self._wallpaper_daemon = QCheckBox("Run wallpaper watcher at login (background daemon)")
        self._wallpaper_daemon.setChecked(True)
        self._wallpaper_daemon.setToolTip(
            "Installs ~/.config/autostart/plasmacolorizer-daemon.desktop and polls the "
            "Plasma wallpaper every few seconds — even when this window is closed."
        )
        self._wallpaper_daemon.toggled.connect(self._on_wallpaper_daemon_toggled)
        layout.addWidget(self._wallpaper_daemon)

        daemon_row = QHBoxLayout()
        self._daemon_status = QLabel()
        self._daemon_status.setWordWrap(True)
        restart_daemon = QPushButton("Restart watcher")
        restart_daemon.setObjectName("secondary")
        restart_daemon.clicked.connect(self._on_restart_wallpaper_daemon)
        daemon_row.addWidget(self._daemon_status, 1)
        daemon_row.addWidget(restart_daemon)
        layout.addLayout(daemon_row)

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
            "Restart Plasma shell afterward (optional; brief flicker — can break the desktop)"
        )
        self._restart_plasma.setChecked(False)
        self._restart_plasma.setToolTip(
            "Soft apply (plasma-apply-colorscheme + DBus) is enough for most updates and is safe.\n\n"
            "A full plasmashell restart reloads panel/Kickoff caches, but quitting the shell "
            "via kquitapp has left Plasma dead on this machine when systemd's "
            "plasma-plasmashell.service (--no-respawn) did not recover. "
            "Prefer leaving this unchecked; use Recover Plasma desktop if the shell dies."
        )
        layout.addWidget(self._restart_plasma)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        wrap = QWidget()
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.addWidget(scroll)

        self._clear_swatches()
        self._load_app_settings_to_ui()
        self._update_component_color_swatches()
        return wrap

    def _build_log_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        hint = QLabel(
            f"Session log (also written to <code>{self._log_file}</code>). "
            "Open this tab during long apply runs."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(hint)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(300)
        layout.addWidget(self._log, 1)
        open_btn = QPushButton("Open log file")
        open_btn.setObjectName("secondary")
        open_btn.clicked.connect(self._on_open_log_file)
        layout.addWidget(open_btn)
        return wrap

    def _on_open_log_file(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_file)))

    def _update_panel_opacity_repair_btn(self) -> None:
        if hasattr(self, "_panel_opacity_repair_btn"):
            self._panel_opacity_repair_btn.setEnabled(plasma_scheme.theme_plasmarc_needs_repair())

    def _on_diagnose_panel_opacity(self) -> None:
        diagnostics = plasma_scheme.run_panel_opacity_diagnostics(self._app_settings_from_ui())
        self._append_log("Panel opacity diagnostics:")
        for line in plasma_scheme.format_panel_opacity_diagnostics(diagnostics):
            self._append_log(f"  {line}")
        self._update_panel_opacity_repair_btn()
        failures = [
            d for d in diagnostics
            if d.severity == plasma_scheme.DiagnosticSeverity.FAIL
        ]
        if failures:
            QMessageBox.warning(
                self,
                "Panel opacity issue detected",
                "Diagnostics found problems that can block visible panel opacity modes:\n\n- "
                + "\n\n- ".join(d.message for d in failures)
                + "\n\nUse Repair theme for panel opacity if needed, then re-test Solid vs Translucent.",
            )

    def _on_repair_panel_opacity(self) -> None:
        self._append_log("Repairing PlasmaColorizer theme for panel opacity…")
        try:
            ok, msg = plasma_scheme.repair_plasma_theme_for_panel_opacity()
            self._append_log(msg)
            if not ok:
                self._append_log(
                    "Repair completed with errors — check the log. "
                    "If needed: systemctl --user restart plasma-plasmashell.service",
                )
        except OSError as exc:
            self._append_log(f"Repair failed: {exc}")
            return
        self._on_diagnose_panel_opacity()

    def _plasma_panel_opacity_mode_from_ui(self) -> str:
        mode = self._plasma_panel_opacity_combo.currentData()
        return str(mode) if mode else "opaque"

    def _set_plasma_panel_opacity_combo(self, mode: str) -> None:
        target = mode.strip().lower()
        self._plasma_panel_opacity_combo.blockSignals(True)
        for i in range(self._plasma_panel_opacity_combo.count()):
            if self._plasma_panel_opacity_combo.itemData(i) == target:
                self._plasma_panel_opacity_combo.setCurrentIndex(i)
                break
        self._plasma_panel_opacity_combo.blockSignals(False)

    def _on_plasma_panel_opacity_mode_changed(self, _index: int) -> None:
        mode = str_to_panel_opacity_mode(self._plasma_panel_opacity_mode_from_ui())
        mode_name = plasma_scheme.panel_opacity_mode_to_str(mode)
        if mode_name == "translucent":
            reply = QMessageBox.warning(
                self,
                "Translucent panel",
                "Translucent mode can make a dark panel look like it disappeared "
                "(wallpaper shows through), even though Plasma is still running.\n\n"
                "Prefer Solid unless you specifically want see-through panels.\n\n"
                "Continue with Translucent?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._set_plasma_panel_opacity_combo("opaque")
                return
        self._save_app_settings_from_ui()
        self._append_log(
            f"Applying panel opacity → {mode_name} ({int(mode)})…",
        )
        try:
            ok, msg = plasma_scheme.apply_plasma_panel_opacity_live(mode)
            self._append_log(msg)
            if not ok:
                self._append_log(
                    "Panel opacity was saved to plasmashellrc. "
                    "If the look did not change, run once: "
                    "systemctl --user restart plasma-plasmashell.service",
                )
        except OSError as exc:
            self._append_log(f"Panel opacity apply failed: {exc}")

        overriders = plasma_scheme.detect_competing_panel_tools()
        if overriders:
            for note in overriders:
                self._append_log(f"Note: {note}")
            QMessageBox.warning(
                self,
                "Panel opacity may be overridden",
                "PlasmaColorizer applied the panel opacity mode, but another tool is painting "
                "your panel background, so the change may not be visible:\n\n- "
                + "\n\n- ".join(overriders)
                + "\n\nDisable or pause that tool, then try the opacity mode again.",
            )
        self._update_panel_opacity_repair_btn()

    def _load_app_settings_to_ui(self) -> None:
        app = load_app_settings()
        sys_mode = plasma_scheme.read_plasma_panel_opacity_mode()
        mode = app.plasma_panel_opacity_mode
        if sys_mode is not None:
            mode = plasma_scheme.panel_opacity_mode_to_str(sys_mode)
        self._plasma_strong_panel_tint.setChecked(app.plasma_strong_panel_tint)
        self._set_plasma_panel_opacity_combo(mode)
        self._component_overrides = overrides_from_settings_dict(app.plasma_component_colors)
        if self._component_overrides:
            self._component_colors_toggle.setChecked(True)
        self._apply_konsole_scheme.setChecked(app.apply_konsole_scheme)
        self._dolphin_follow_system.setChecked(app.dolphin_follow_system_colorscheme)
        self._auto_apply_wallpaper.blockSignals(True)
        self._auto_apply_wallpaper.setChecked(app.auto_apply_on_wallpaper_change)
        self._auto_apply_wallpaper.blockSignals(False)
        self._wallpaper_daemon.blockSignals(True)
        self._wallpaper_daemon.setChecked(app.wallpaper_daemon_enabled)
        self._wallpaper_daemon.blockSignals(False)
        self._monitor.setValue(app.wallpaper_monitor)
        self._quality.setValue(app.quantizer_quality)
        self._primary_bias_slider.setValue(int(round(app.primary_bias_strength * 100)))
        self._set_dark_mode_combo(app.dark_mode)
        self._set_combo_data(self._accent_combo, app.scheme_accent)
        self._set_combo_data(self._emphasis_combo, app.scheme_emphasis)
        if app.scheme_links:
            self._set_combo_data(self._links_combo, app.scheme_links)
        else:
            self._links_combo.setCurrentIndex(0)
        self._restart_plasma.setChecked(app.restart_plasma_after_apply)

    def _set_dark_mode_combo(self, mode: str) -> None:
        key = (mode or "follow").strip().lower()
        idx = {"follow": 0, "dark": 1, "light": 2}.get(key, 0)
        self._dark_combo.setCurrentIndex(idx)

    def _dark_mode_from_ui(self) -> str:
        idx = self._dark_combo.currentIndex()
        if idx == 1:
            return "dark"
        if idx == 2:
            return "light"
        return "follow"

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _scheme_links_from_ui(self) -> str:
        data = self._links_combo.currentData()
        return data if isinstance(data, str) else ""

    def _app_settings_from_ui(self) -> AppSettings:
        prev = load_app_settings()
        return AppSettings(
            plasma_fallback_theme_id=prev.plasma_fallback_theme_id,
            plasma_panel_opacity_mode=self._plasma_panel_opacity_mode_from_ui(),
            plasma_strong_panel_tint=self._plasma_strong_panel_tint.isChecked(),
            plasma_component_colors=overrides_to_settings_dict(self._component_overrides),
            apply_konsole_scheme=self._apply_konsole_scheme.isChecked(),
            dolphin_follow_system_colorscheme=self._dolphin_follow_system.isChecked(),
            auto_apply_on_wallpaper_change=self._auto_apply_wallpaper.isChecked(),
            wallpaper_daemon_enabled=self._wallpaper_daemon.isChecked(),
            wallpaper_daemon_poll_interval_s=prev.wallpaper_daemon_poll_interval_s,
            wallpaper_monitor=self._monitor.value(),
            quantizer_quality=self._quality.value(),
            primary_bias_strength=self._primary_bias_slider.value() / 100.0,
            dark_mode=self._dark_mode_from_ui(),
            scheme_accent=str(self._accent_combo.currentData() or "primary"),
            scheme_emphasis=str(self._emphasis_combo.currentData() or "secondary"),
            scheme_links=self._scheme_links_from_ui(),
            restart_plasma_after_apply=self._restart_plasma.isChecked(),
        )

    def _save_app_settings_from_ui(self) -> None:
        save_app_settings(self._app_settings_from_ui())

    def _sync_wallpaper_watchers(self) -> None:
        if not hasattr(self, "_wallpaper_poll_timer"):
            return
        app = load_app_settings()
        if app.wallpaper_daemon_enabled and app.auto_apply_on_wallpaper_change:
            self._wallpaper_poll_timer.stop()
            self._ensure_wallpaper_daemon_running()
        elif app.auto_apply_on_wallpaper_change:
            if not self._wallpaper_poll_timer.isActive():
                self._wallpaper_poll_timer.start()
        else:
            self._wallpaper_poll_timer.stop()

    def _ensure_wallpaper_daemon_running(self) -> None:
        if not self._wallpaper_daemon.isChecked():
            return
        wallpaper_daemon.install_autostart()
        if wallpaper_daemon.is_daemon_running():
            return
        import subprocess
        import sys

        try:
            subprocess.Popen(
                [sys.executable, "-m", "plasmacolorizer.wallpaper_daemon"],
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self._logger.warning("Could not start wallpaper daemon: %s", exc)

    def _update_daemon_status_label(self) -> None:
        if self._wallpaper_daemon.isChecked():
            running = wallpaper_daemon.is_daemon_running()
            autostart = wallpaper_daemon.autostart_installed()
            parts = [
                "Watcher: running" if running else "Watcher: not running",
                "autostart on" if autostart else "autostart off",
            ]
            self._daemon_status.setText(" · ".join(parts))
        else:
            self._daemon_status.setText("Background watcher disabled — in-app polling only when open.")

    def _on_wallpaper_daemon_toggled(self, enabled: bool) -> None:
        self._save_app_settings_from_ui()
        if not hasattr(self, "_wallpaper_poll_timer"):
            self._update_daemon_status_label()
            return
        if enabled:
            wallpaper_daemon.install_autostart()
            self._ensure_wallpaper_daemon_running()
            self._wallpaper_poll_timer.stop()
        else:
            wallpaper_daemon.stop_daemon()
            wallpaper_daemon.uninstall_autostart()
            if self._auto_apply_wallpaper.isChecked():
                self._wallpaper_poll_timer.start()
        self._update_daemon_status_label()

    def _on_restart_wallpaper_daemon(self) -> None:
        self._save_app_settings_from_ui()
        wallpaper_daemon.stop_daemon()
        if self._wallpaper_daemon.isChecked():
            self._ensure_wallpaper_daemon_running()
        self._update_daemon_status_label()
        self._append_log("Wallpaper watcher restarted.")

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
            strong_panel_tint=self._plasma_strong_panel_tint.isChecked(),
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

    def _refresh_color_previews(self, pal: MaterialPalette | None = None) -> None:
        self._update_palette_swatches(pal)
        self._update_component_color_swatches()
        if hasattr(self, "_term_preview"):
            self._term_update_preview()

    def _effective_scheme_sections(self) -> dict[str, dict[str, str]] | None:
        eff = self._effective_palette()
        if eff is None:
            return None
        sections = plasma_scheme.build_color_sections(eff, self._scheme_choices())
        return apply_component_color_overrides(
            sections,
            self._component_overrides,
            palette=eff,
        )

    def _update_component_color_swatches(self) -> None:
        eff = self._effective_palette()
        sections = None
        if eff is not None:
            sections = plasma_scheme.build_color_sections(eff, self._scheme_choices())
        for comp in PLASMA_COMPONENTS:
            btn = self._component_buttons.get(comp.id)
            reset = self._component_reset_buttons.get(comp.id)
            if btn is None:
                continue
            override = self._component_overrides.get(comp.id)
            if override is not None and eff is not None:
                rgb = resolve_override_rgb(override, eff)
            elif sections is not None and eff is not None:
                rgb = effective_component_rgb(comp.id, sections, eff)
            else:
                rgb = None
            if rgb is None:
                btn.setStyleSheet(
                    "QToolButton { background: #2a2a32; border: 1px solid #444; border-radius: 6px; }"
                )
                btn.setToolTip(component_tooltip(comp.id, sections=sections, palette=eff, override=override))
            else:
                hx = rgb_to_hex(rgb)
                border = "#c9a227" if override is not None else "#555"
                btn.setStyleSheet(
                    f"QToolButton {{ background-color: {hx}; border: 2px solid {border}; "
                    "border-radius: 6px; }}"
                )
                btn.setToolTip(component_tooltip(comp.id, sections=sections, palette=eff, override=override))
            if reset is not None:
                reset.setEnabled(override is not None)

    def _edit_component_color(self, comp_id: str) -> None:
        comp = COMPONENT_BY_ID.get(comp_id)
        eff = self._effective_palette()
        if comp is None or eff is None:
            QMessageBox.information(
                self,
                "Component colors",
                "Preview a palette first, then you can override individual component colours.",
            )
            return
        dlg = ComponentColorDialog(
            self,
            component=comp,
            palette=eff,
            current=self._component_overrides.get(comp_id),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dlg.selected_override()
        if chosen is None:
            return
        self._component_overrides[comp_id] = chosen
        self._save_app_settings_from_ui()
        self._update_component_color_swatches()
        self._append_log(f"Component override: {comp.label} ({chosen.source})")

    def _reset_component_color(self, comp_id: str) -> None:
        if comp_id not in self._component_overrides:
            return
        comp = COMPONENT_BY_ID.get(comp_id)
        del self._component_overrides[comp_id]
        self._save_app_settings_from_ui()
        self._update_component_color_swatches()
        label = comp.label if comp else comp_id
        self._append_log(f"Component {label} reset to automated mapping.")

    def _reset_all_component_colors(self) -> None:
        if not self._component_overrides:
            return
        self._component_overrides.clear()
        self._save_app_settings_from_ui()
        self._update_component_color_swatches()
        self._append_log("All component colour overrides cleared.")

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
        self._refresh_color_previews()
        self._append_log(f"Swatch override {key}={rgb_to_hex(self._swatch_overrides[key])}")

    def _on_swatch_context_menu(self, key: str, global_pos: QPoint) -> None:
        menu = QMenu(self)
        reset_one = menu.addAction(f"Reset “{key}” to generated")
        chosen = menu.exec(global_pos)
        if chosen is reset_one and key in self._swatch_overrides:
            del self._swatch_overrides[key]
            self._refresh_color_previews()
            self._append_log(f"Swatch {key} reset to generated palette.")

    def _on_reset_swatches(self) -> None:
        if not self._swatch_overrides:
            return
        self._swatch_overrides.clear()
        if self._last_palette is not None:
            self._refresh_color_previews(self._last_palette)
        else:
            self._clear_swatches()
            self._update_component_color_swatches()
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
            self._last_wallpaper_fingerprint = wallpaper_fingerprint_for_path(path)
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
        self._last_wallpaper_fingerprint = wallpaper_fingerprint_for_path(src)
        self._start_preview_palette(src)

    def _on_wallpaper_poll_tick(self) -> None:
        if wallpaper_watch_skipped(self._manual_path.text()):
            return
        if self._thread is not None and self._thread.isRunning():
            return
        fp = wallpaper_fingerprint(self._monitor.value())
        if fp is None:
            return
        if self._last_wallpaper_fingerprint is None:
            self._last_wallpaper_fingerprint = fp
            return
        if fp == self._last_wallpaper_fingerprint:
            return
        try:
            path = wp.current_wallpaper_image_path(self._monitor.value())
        except (FileNotFoundError, OSError):
            return
        self._pending_wallpaper_path = path
        self._wallpaper_debounce_timer.start()

    def _on_wallpaper_change_debounced(self) -> None:
        path = self._pending_wallpaper_path
        self._pending_wallpaper_path = None
        if not path:
            return
        fp = wallpaper_fingerprint_for_path(path)
        if fp == self._last_wallpaper_fingerprint:
            return
        self._last_wallpaper_fingerprint = fp
        self._path_display.setText(path)
        self._last_wallpaper_src = path
        self._append_log(f"[auto] Wallpaper changed: {path}")
        if not self._auto_apply_wallpaper.isChecked():
            self._append_log("[auto] Auto-apply disabled — use Generate and apply manually.")
            return
        if self._thread is not None and self._thread.isRunning():
            self._append_log("[auto] Worker busy — will not queue another apply.")
            return
        self._append_log("[auto] Re-applying palette for new wallpaper…")
        self._suppress_apply_dialogs = True
        self._on_generate()

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
            primary_bias_strength=self._primary_bias_slider.value() / 100.0,
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
        self._update_component_color_swatches()
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
        self._save_app_settings_from_ui()
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
            app_settings=self._app_settings_from_ui(),
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
        self._save_app_settings_from_ui()
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
            primary_bias_strength=self._primary_bias_slider.value() / 100.0,
            dark=self._dark_choice(),
            quality=self._quality.value(),
            choices=self._scheme_choices(),
            swatch_overrides=dict(self._swatch_overrides),
            app_settings=self._app_settings_from_ui(),
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
        self._update_component_color_swatches()
        pri = result.palette.colors.get("primary", (0, 0, 0))
        self._append_log(f"Palette ready: primary={rgb_to_hex(pri)}, dark={result.palette.is_dark}")
        self._refresh_running_conkys()

        if not result.apply_ok:
            self._append_log(f"Apply error: {result.apply_error}")
            if not self._suppress_apply_dialogs:
                QMessageBox.warning(
                    self,
                    "PlasmaColorizer",
                    f"Scheme file was written to:\n{result.scheme_path}\n\n"
                    f"But colors could not be written to ~/.config/kdeglobals:\n{result.apply_error}\n\n"
                    "Open System Settings -> Appearance -> Colors and pick "
                    f"\"{plasma_scheme.SCHEME_FILE_STEM}\" manually.",
                )
            self._suppress_apply_dialogs = False
            return

        if result.konsole_error:
            self._append_log(f"Konsole theming: {result.konsole_error}")
        if result.dolphin_error:
            self._append_log(f"Dolphin theming: {result.dolphin_error}")
        elif getattr(result, "dolphin_note", ""):
            self._append_log(f"Dolphin: {result.dolphin_note}")

        # kdeglobals write succeeded; push palette to KWin, shell, and global accent (main thread).
        app = self._app_settings_from_ui()
        for note in plasma_scheme.collect_apply_diagnostics(app):
            self._append_log(f"Note: {note}")
        self._append_log(
            "Soft-refresh: plasma-apply-colorscheme + KWin + accent "
            "(desktoptheme / refreshCurrentShell skipped — safe mode)…"
        )
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
            if not rs_ok:
                self._append_log(
                    "WARN: plasmashell restart failed — run: "
                    "systemctl --user start plasma-plasmashell.service"
                    "  or: plasmacolorizer-recover"
                )

        self._save_app_settings_from_ui()
        try:
            self._last_wallpaper_fingerprint = wallpaper_fingerprint_for_path(str(result.src))
            record_applied_wallpaper_fingerprint(str(result.src))
        except OSError:
            pass
        self._ensure_wallpaper_daemon_running()
        self._sync_wallpaper_watchers()
        self._update_daemon_status_label()

        if self._suppress_apply_dialogs:
            self._suppress_apply_dialogs = False
            if notify_ok:
                self._append_log("[auto] Palette re-applied for new wallpaper.")
            return

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
        if hasattr(self, "_wallpaper_poll_timer"):
            self._wallpaper_poll_timer.stop()
        if hasattr(self, "_wallpaper_debounce_timer"):
            self._wallpaper_debounce_timer.stop()
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

    # --- Terminal tab --------------------------------------------------
    def _build_terminal_tab(self) -> QWidget:
        self._term_overrides: dict[str, str] = {
            "background": "",
            "foreground": "",
            "accent": "",
        }

        wrap = QWidget()
        root = QVBoxLayout(wrap)

        intro = QLabel(
            "Theme your terminal from the current wallpaper palette. Colors follow "
            "the Colorizer tab automatically; the controls below let you tweak the "
            "font, transparency, and pin specific colors. <b>Konsole</b> is the KDE "
            "default; other terminals appear here when they're installed."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(intro)

        term_box = QGroupBox("Terminal")
        term_form = QFormLayout()
        self._term_combo = QComboBox()
        installed = set(terminal_backends.installed_terminals())
        for tid, backend in terminal_backends.TERMINALS.items():
            is_here = tid in installed
            label = backend.label if is_here else f"{backend.label}  (not installed)"
            self._term_combo.addItem(label, tid)
            if not is_here and tid != "konsole":
                idx = self._term_combo.count() - 1
                model = self._term_combo.model()
                model.item(idx).setEnabled(False)
        self._term_combo.currentIndexChanged.connect(self._term_update_preview)
        term_form.addRow("Terminal", self._term_combo)
        term_box.setLayout(term_form)
        root.addWidget(term_box)

        appearance = QGroupBox("Font & transparency")
        appearance_form = QFormLayout()

        self._term_font_enabled = QCheckBox("Use a custom font")
        self._term_font_enabled.toggled.connect(self._on_term_font_toggled)
        appearance_form.addRow("", self._term_font_enabled)

        self._term_font_combo = QFontComboBox()
        self._term_font_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self._term_font_combo.currentFontChanged.connect(self._term_update_preview)
        appearance_form.addRow("Font family", self._term_font_combo)

        self._term_font_size = QDoubleSpinBox()
        self._term_font_size.setRange(5.0, 72.0)
        self._term_font_size.setDecimals(1)
        self._term_font_size.setSingleStep(0.5)
        self._term_font_size.setValue(11.0)
        self._term_font_size.valueChanged.connect(self._term_update_preview)
        appearance_form.addRow("Font size", self._term_font_size)

        self._term_bold_intense = QCheckBox(
            "Use bright colors for bold text (BoldIntenseColors)"
        )
        self._term_bold_intense.setChecked(True)
        self._term_bold_intense.toggled.connect(self._term_update_preview)
        appearance_form.addRow("", self._term_bold_intense)

        self._term_opacity = QSlider(Qt.Orientation.Horizontal)
        self._term_opacity.setRange(0, 100)
        self._term_opacity.setValue(100)
        self._term_opacity.setToolTip(
            "Terminal background opacity. 100% is solid; lower values let the "
            "wallpaper show through (needs a compositor)."
        )
        self._term_opacity_label = QLabel("100%")
        self._term_opacity_label.setMinimumWidth(44)
        self._term_opacity.valueChanged.connect(self._on_term_opacity_changed)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._term_opacity, 1)
        opacity_row.addWidget(self._term_opacity_label)
        appearance_form.addRow("Background opacity", opacity_row)
        appearance.setLayout(appearance_form)
        root.addWidget(appearance)

        colors = QGroupBox("Color overrides")
        colors_layout = QVBoxLayout()
        ch = QLabel(
            "Leave these off to derive every color from the wallpaper. Turn one on "
            "to pin a specific background, text, or accent (cursor) color."
        )
        ch.setWordWrap(True)
        colors_layout.addWidget(ch)

        self._term_color_checks: dict[str, QCheckBox] = {}
        self._term_color_buttons: dict[str, QToolButton] = {}
        for key, label in (
            ("background", "Background"),
            ("foreground", "Text"),
            ("accent", "Accent / cursor"),
        ):
            row = QHBoxLayout()
            check = QCheckBox(f"Custom {label.lower()}")
            check.toggled.connect(lambda _c, k=key: self._on_term_override_toggled(k))
            btn = QToolButton()
            btn.setFixedSize(QSize(48, 24))
            btn.setToolTip(f"Click to choose the {label.lower()} color")
            btn.clicked.connect(lambda _c=False, k=key: self._term_pick_color(k))
            self._term_color_checks[key] = check
            self._term_color_buttons[key] = btn
            row.addWidget(check)
            row.addWidget(btn)
            row.addStretch(1)
            colors_layout.addLayout(row)
        colors.setLayout(colors_layout)
        root.addWidget(colors)

        preview_box = QGroupBox("Preview")
        preview_layout = QVBoxLayout()
        self._term_preview = QTextEdit()
        self._term_preview.setReadOnly(True)
        self._term_preview.setMinimumHeight(150)
        preview_layout.addWidget(self._term_preview)
        preview_box.setLayout(preview_layout)
        root.addWidget(preview_box)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply to terminal")
        apply_btn.setToolTip("Write the scheme and reload the selected terminal now.")
        apply_btn.clicked.connect(self._term_apply_clicked)
        save_btn = QPushButton("Save settings")
        save_btn.setObjectName("secondary")
        save_btn.clicked.connect(self._term_save_clicked)
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setObjectName("secondary")
        reset_btn.clicked.connect(self._term_reset_clicked)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)
        root.addStretch(1)

        self._term_load_into_fields(load_terminal_settings())
        return wrap

    def _combo_select_data(self, combo: QComboBox, value: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _term_load_into_fields(self, s: TerminalSettings) -> None:
        widgets = (
            self._term_combo,
            self._term_font_enabled,
            self._term_font_combo,
            self._term_font_size,
            self._term_bold_intense,
            self._term_opacity,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            self._combo_select_data(self._term_combo, s.terminal_id)
            has_font = bool(s.font_family)
            self._term_font_enabled.setChecked(has_font)
            if has_font:
                self._term_font_combo.setCurrentFont(QFont(s.font_family))
            self._term_font_combo.setEnabled(has_font)
            self._term_font_size.setValue(float(s.font_size))
            self._term_bold_intense.setChecked(bool(s.bold_intense))
            pct = max(0, min(100, round(float(s.opacity) * 100)))
            self._term_opacity.setValue(pct)
            self._term_opacity_label.setText(f"{pct}%")
            self._term_overrides = {
                "background": s.background_override,
                "foreground": s.foreground_override,
                "accent": s.accent_override,
            }
        finally:
            for w in widgets:
                w.blockSignals(False)
        for key, value in self._term_overrides.items():
            check = self._term_color_checks[key]
            check.blockSignals(True)
            check.setChecked(bool(value))
            check.blockSignals(False)
            self._term_color_buttons[key].setEnabled(bool(value))
        self._refresh_term_color_buttons()
        self._term_update_preview()

    def _on_term_font_toggled(self, checked: bool) -> None:
        self._term_font_combo.setEnabled(checked)
        self._term_update_preview()

    def _on_term_opacity_changed(self, value: int) -> None:
        self._term_opacity_label.setText(f"{value}%")
        self._term_update_preview()

    def _on_term_override_toggled(self, key: str) -> None:
        checked = self._term_color_checks[key].isChecked()
        self._term_color_buttons[key].setEnabled(checked)
        if not checked:
            self._term_overrides[key] = ""
        elif not self._term_overrides.get(key):
            # Seed the override from the current effective color so the picker starts there.
            self._term_overrides[key] = self._term_effective_hex(key) or "#1e1e28"
        self._refresh_term_color_buttons()
        self._term_update_preview()

    def _term_effective_hex(self, key: str) -> str:
        pal = self._effective_palette()
        if pal is None:
            return ""
        colors = terminal_backends.resolve_terminal_colors(
            pal, self._term_settings_from_fields()
        )
        rgb = {
            "background": colors.background,
            "foreground": colors.foreground,
            "accent": colors.cursor,
        }[key]
        return rgb_to_hex(rgb)

    def _term_pick_color(self, key: str) -> None:
        current = self._term_overrides.get(key) or self._term_effective_hex(key) or "#1e1e28"
        rgb = parse_hex_rgb(current) or (30, 30, 40)
        chosen = QColorDialog.getColor(
            QColor(*rgb), self, f"Choose {key} color"
        )
        if not chosen.isValid():
            return
        self._term_overrides[key] = chosen.name()
        self._term_color_checks[key].setChecked(True)
        self._term_color_buttons[key].setEnabled(True)
        self._refresh_term_color_buttons()
        self._term_update_preview()

    def _refresh_term_color_buttons(self) -> None:
        for key, btn in self._term_color_buttons.items():
            hexv = self._term_overrides.get(key) or self._term_effective_hex(key)
            if hexv:
                btn.setStyleSheet(
                    f"QToolButton {{ background-color: {hexv}; "
                    "border: 1px solid #555; border-radius: 4px; }}"
                )
                btn.setToolTip(f"{key}: {hexv}")
            else:
                btn.setStyleSheet(
                    "QToolButton { background: #2a2a32; border: 1px solid #444; "
                    "border-radius: 4px; }"
                )

    def _term_settings_from_fields(self) -> TerminalSettings:
        font_family = ""
        if self._term_font_enabled.isChecked():
            font_family = self._term_font_combo.currentFont().family()
        return TerminalSettings(
            terminal_id=str(self._term_combo.currentData() or "konsole"),
            font_family=font_family,
            font_size=float(self._term_font_size.value()),
            bold_intense=bool(self._term_bold_intense.isChecked()),
            background_override=self._term_overrides.get("background", ""),
            foreground_override=self._term_overrides.get("foreground", ""),
            accent_override=self._term_overrides.get("accent", ""),
            opacity=self._term_opacity.value() / 100.0,
        )

    def _term_update_preview(self, *_args) -> None:
        if not hasattr(self, "_term_preview"):
            return
        self._refresh_term_color_buttons()
        pal = self._effective_palette()
        if pal is None:
            self._term_preview.setHtml(
                "<i>Generate a palette on the Colorizer tab to preview the terminal.</i>"
            )
            return
        settings = self._term_settings_from_fields()
        colors = terminal_backends.resolve_terminal_colors(pal, settings)
        bg = rgb_to_hex(colors.background)
        fg = rgb_to_hex(colors.foreground)
        cursor = rgb_to_hex(colors.cursor)
        family = colors.font_family or "monospace"
        size = colors.font_size

        def swatches(row: list) -> str:
            return "".join(
                f'<span style="color:{rgb_to_hex(c)}">&#9608;&#9608; </span>' for c in row
            )

        green = rgb_to_hex(colors.normal[2])
        blue = rgb_to_hex(colors.normal[4])
        bright_blue = rgb_to_hex(colors.bright[4])
        html = (
            f'<div style="background-color:{bg}; color:{fg}; padding:10px; '
            f'font-family:\'{family}\'; font-size:{size:g}pt; border-radius:6px;">'
            f'<div><span style="color:{green}">user@host</span>'
            f'<span style="color:{fg}">:</span>'
            f'<span style="color:{blue}">~/projects</span>'
            f'<span style="color:{cursor}">$</span> ls --color<br>'
            f'{swatches(colors.normal)}<br>{swatches(colors.bright)}</div>'
            f'<div style="color:{fg}">The quick brown fox — normal text</div>'
            f'<div style="color:{bright_blue}"><b>Bold / bright accent line</b></div>'
            f'</div>'
        )
        self._term_preview.setHtml(html)

    def _term_apply_clicked(self) -> None:
        pal = self._require_palette()
        if pal is None:
            return
        settings = self._term_settings_from_fields()
        save_terminal_settings(settings)
        backend = terminal_backends.TERMINALS.get(settings.terminal_id)
        if backend is not None and settings.terminal_id != "konsole" and not backend.is_installed():
            QMessageBox.warning(
                self,
                "Terminal",
                f"{backend.label} is not installed.",
            )
            return
        ok, msg = terminal_backends.apply_terminal_theme(pal, settings)
        self._append_log(f"Terminal apply: {msg}")
        if ok:
            QMessageBox.information(self, "Terminal", f"Applied.\n{msg}")
        else:
            QMessageBox.warning(self, "Terminal", f"Apply reported a problem:\n{msg}")

    def _term_save_clicked(self) -> None:
        settings = self._term_settings_from_fields()
        path = save_terminal_settings(settings)
        self._append_log(f"Terminal settings saved to {path}")
        QMessageBox.information(self, "Terminal", f"Settings saved to:\n{path}")

    def _term_reset_clicked(self) -> None:
        self._term_load_into_fields(TerminalSettings())

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

        self._conky_theme_combo = QComboBox()
        for theme in conky_themes.theme_choices():
            self._conky_theme_combo.addItem(theme.label, theme.theme_id)
        self._conky_theme_combo.setToolTip(
            "Bundled visual style for all Conky presets. Themes change fonts, section "
            "headings, dividers, and (for the System preset) whether CPU/RAM are drawn "
            "as text, bars, or graphs. Palette colors are unchanged."
        )
        self._conky_theme_combo.currentIndexChanged.connect(self._on_conky_theme_changed)

        self._conky_window_mode = QComboBox()
        self._conky_window_mode.addItem(
            "Normal + below (visible on Plasma — recommended)", "normal_below"
        )
        self._conky_window_mode.addItem(
            "Desktop layer (often invisible under Plasma wallpaper)", "desktop"
        )
        self._conky_window_mode.setToolTip(
            "How bundled Conky windows attach to Plasma.\n\n"
            "Normal + below: visible above the wallpaper, under other windows. "
            "Recommended on Plasma Wayland.\n\n"
            "Desktop layer: sits under plasmashell's wallpaper surface — Conky "
            "keeps running but the panel looks like it died. Avoid on Plasma."
        )

        self._conky_panel_transparency = QSlider(Qt.Orientation.Horizontal)
        self._conky_panel_transparency.setRange(0, 100)
        self._conky_panel_transparency.setValue(25)
        self._conky_panel_transparency.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._conky_panel_transparency.setTickInterval(25)
        self._conky_panel_transparency.setToolTip(
            "Real ARGB transparency for bundled Conky panels. "
            "0% = solid surface, 100% = fully see-through (only the text/widgets remain). "
            "Panels run as ``normal`` windows pinned below everything so KWin tracks "
            "damage events properly (no ghosting under window overlap) while still "
            "keeping every real application window above them."
        )
        self._conky_panel_transparency_label = QLabel("25%")
        self._conky_panel_transparency_label.setMinimumWidth(40)
        self._conky_panel_transparency.valueChanged.connect(
            self._on_panel_transparency_changed,
        )
        transparency_row = QHBoxLayout()
        transparency_row.addWidget(self._conky_panel_transparency, 1)
        transparency_row.addWidget(self._conky_panel_transparency_label)

        settings_form.addRow("ESV API key", self._conky_esv_key)
        settings_form.addRow("Weather quick pick", quick_row)
        settings_form.addRow("Weather city", self._conky_weather_city)
        settings_form.addRow("Weather lat, lon", self._conky_weather_latlon)
        settings_form.addRow("Weather temperature", self._conky_weather_temp_unit)
        settings_form.addRow("Conky theme", self._conky_theme_combo)
        settings_form.addRow('System preset: CPU / RAM', self._conky_system_stats_style)
        settings_form.addRow("Bundled panel transparency", transparency_row)
        settings_form.addRow("Panel window mode", self._conky_window_mode)
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
        recover_btn = QPushButton("Recover Plasma desktop")
        recover_btn.setObjectName("secondary")
        recover_btn.setToolTip(
            "Emergency: stop all Conky panels, disable Conky login autostart, "
            "stop the wallpaper daemon, and restart plasmashell if it is missing. "
            "Does not change colour schemes."
        )
        recover_btn.clicked.connect(self._conky_recover_desktop_clicked)
        apply_row.addWidget(apply_colors)
        apply_row.addWidget(stop_all)
        apply_row.addWidget(recover_btn)
        apply_row.addStretch(1)
        bundled_layout.addLayout(apply_row)

        self._conky_autostart_check = QCheckBox(
            "Auto-start running Conkys at login (remember last state)"
        )
        self._conky_autostart_check.setToolTip(
            "Installs ~/.config/autostart/plasmacolorizer-conky.desktop. "
            "On login it spawns whichever bundled presets were running in your last session, "
            "using the last rendered configs in ~/.local/share/plasmacolorizer/conky/rendered/."
        )
        self._conky_autostart_check.toggled.connect(self._on_conky_autostart_toggled)
        bundled_layout.addWidget(self._conky_autostart_check)

        bundled.setLayout(bundled_layout)
        root.addWidget(bundled)

        root.addWidget(self._build_conky_shortcuts_group())

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
        self._conky_status_timer = QTimer(self)
        self._conky_status_timer.setInterval(2500)
        self._conky_status_timer.timeout.connect(self._refresh_conky_status_labels)
        self._conky_status_timer.start()
        return wrap

    def _build_conky_shortcuts_group(self) -> QGroupBox:
        box = QGroupBox("Shortcuts widget")
        layout = QVBoxLayout()

        hint = QLabel(
            "Rows for the bundled <b>Shortcuts</b> preset. Edit inline, then "
            "<b>Save shortcuts</b> and restart the preset (or use "
            "<b>Apply colors to running Conkys</b>) to see changes."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(hint)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(180)
        self._conky_shortcuts_table = table
        layout.addWidget(table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add shortcut")
        add_btn.setObjectName("secondary")
        add_btn.clicked.connect(self._conky_shortcut_add_row)
        remove_btn = QPushButton("Remove selected")
        remove_btn.setObjectName("secondary")
        remove_btn.clicked.connect(self._conky_shortcut_remove_selected)
        up_btn = QPushButton("Move up")
        up_btn.setObjectName("secondary")
        up_btn.clicked.connect(lambda: self._conky_shortcut_move(-1))
        down_btn = QPushButton("Move down")
        down_btn.setObjectName("secondary")
        down_btn.clicked.connect(lambda: self._conky_shortcut_move(1))
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setObjectName("secondary")
        reset_btn.clicked.connect(self._conky_shortcut_reset_defaults)
        for b in (add_btn, remove_btn, up_btn, down_btn, reset_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        save_row = QHBoxLayout()
        save_btn = QPushButton("Save shortcuts")
        save_btn.setObjectName("secondary")
        save_btn.clicked.connect(self._conky_shortcuts_save_clicked)
        save_row.addWidget(save_btn)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        box.setLayout(layout)
        return box

    def _shortcuts_into_table(self, shortcuts: list[ConkyShortcut]) -> None:
        table = self._conky_shortcuts_table
        table.setRowCount(0)
        for sc in shortcuts:
            self._conky_shortcut_append(sc.label, sc.keys)

    def _conky_shortcut_append(self, label: str, keys: str) -> None:
        table = self._conky_shortcuts_table
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(label))
        table.setItem(row, 1, QTableWidgetItem(keys))

    def _conky_shortcut_add_row(self) -> None:
        self._conky_shortcut_append("", "")
        table = self._conky_shortcuts_table
        last = table.rowCount() - 1
        table.setCurrentCell(last, 0)
        table.editItem(table.item(last, 0))

    def _conky_shortcut_remove_selected(self) -> None:
        table = self._conky_shortcuts_table
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)

    def _conky_shortcut_move(self, delta: int) -> None:
        table = self._conky_shortcuts_table
        row = table.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= table.rowCount():
            return
        rows = self._shortcuts_from_table()
        rows[row], rows[target] = rows[target], rows[row]
        self._shortcuts_into_table(rows)
        table.setCurrentCell(target, 0)

    def _conky_shortcut_reset_defaults(self) -> None:
        self._shortcuts_into_table(default_conky_shortcuts())

    def _shortcuts_from_table(self) -> list[ConkyShortcut]:
        table = self._conky_shortcuts_table
        out: list[ConkyShortcut] = []
        for row in range(table.rowCount()):
            label_item = table.item(row, 0)
            keys_item = table.item(row, 1)
            label = (label_item.text() if label_item else "").strip()
            keys = (keys_item.text() if keys_item else "").strip()
            if not label and not keys:
                continue
            out.append(ConkyShortcut(label=label, keys=keys))
        return out

    def _conky_shortcuts_save_clicked(self) -> None:
        settings = load_conky_settings()
        settings.conky_shortcuts = self._shortcuts_from_table()
        path = save_conky_settings(settings)
        self._shortcuts_into_table(settings.conky_shortcuts)
        self._append_log(
            f"Conky shortcuts saved ({len(settings.conky_shortcuts)} entries) to {path}"
        )
        QMessageBox.information(
            self,
            "Conky",
            "Shortcuts saved. Restart the Shortcuts preset (or Apply colors to "
            "running Conkys) to refresh the widget.",
        )

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
        transparency_pct = max(0, min(100, 100 - round(float(s.conky_panel_opacity) * 100)))
        self._conky_panel_transparency.blockSignals(True)
        self._conky_panel_transparency.setValue(transparency_pct)
        self._conky_panel_transparency.blockSignals(False)
        self._conky_panel_transparency_label.setText(f"{transparency_pct}%")
        self._sync_conky_position_combos_from_settings()
        self._shortcuts_into_table(s.conky_shortcuts)
        self._conky_theme_combo.blockSignals(True)
        try:
            for i in range(self._conky_theme_combo.count()):
                if self._conky_theme_combo.itemData(i) == s.conky_theme_id:
                    self._conky_theme_combo.setCurrentIndex(i)
                    break
        finally:
            self._conky_theme_combo.blockSignals(False)
        for i in range(self._conky_window_mode.count()):
            if self._conky_window_mode.itemData(i) == s.conky_window_mode:
                self._conky_window_mode.setCurrentIndex(i)
                break
        self._refresh_system_style_lock()
        self._conky_autostart_check.blockSignals(True)
        self._conky_autostart_check.setChecked(bool(s.autostart_enabled))
        self._conky_autostart_check.blockSignals(False)
        # Reconcile the .desktop entry with the saved preference so toggling matches reality.
        if s.autostart_enabled and not conky_presets.autostart_entry_installed():
            try:
                conky_presets.install_autostart_entry()
            except OSError as exc:
                self._append_log(f"Autostart: could not install entry: {exc}")
        elif not s.autostart_enabled and conky_presets.autostart_entry_installed():
            conky_presets.uninstall_autostart_entry()

    def _on_conky_theme_changed(self, _idx: int) -> None:
        self._refresh_system_style_lock()

    def _on_panel_transparency_changed(self, value: int) -> None:
        """Live preview: as the slider moves, push the new opacity to running Conkys.

        ``_NET_WM_WINDOW_OPACITY`` is the universal compositor opacity hint
        (Conky's own ``own_window_argb_value`` is ignored by KWin/XWayland on
        most setups), so re-applying it gives immediate visible feedback
        without re-rendering / restarting the Conky processes.
        """
        self._conky_panel_transparency_label.setText(f"{value}%")
        opacity = max(0.0, min(1.0, 1.0 - value / 100.0))
        try:
            conky_presets.apply_panel_opacity_to_running(opacity)
        except (OSError, RuntimeError) as exc:  # best-effort live preview
            self._append_log(f"Panel transparency: live update failed: {exc}")

    def _refresh_system_style_lock(self) -> None:
        """When the chosen theme forces a system widget style, lock the user combo to it."""
        theme_id = self._conky_theme_combo.currentData() if self._conky_theme_combo else None
        forced = conky_themes.get_theme(theme_id).system_widget_style
        base_tip = (
            'How the bundled "System" preset draws CPU and RAM. Save, then '
            '"Apply colors to running Conkys" or restart that preset.'
        )
        if forced:
            self._conky_system_stats_style.setEnabled(False)
            for i in range(self._conky_system_stats_style.count()):
                if self._conky_system_stats_style.itemData(i) == forced:
                    self._conky_system_stats_style.blockSignals(True)
                    self._conky_system_stats_style.setCurrentIndex(i)
                    self._conky_system_stats_style.blockSignals(False)
                    break
            self._conky_system_stats_style.setToolTip(
                base_tip + f"\n\nThe current theme forces “{forced}” — change the theme to edit this."
            )
        else:
            self._conky_system_stats_style.setEnabled(True)
            self._conky_system_stats_style.setToolTip(base_tip)

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
        # Mutate the loaded settings so newer fields (autostart, etc.) survive saves.
        settings = load_conky_settings()
        lat, lon = self._parse_lat_lon_field(self._conky_weather_latlon.text())
        settings.esv_api_key = self._conky_esv_key.text().strip()
        settings.weather_city = self._conky_weather_city.text().strip()
        settings.weather_lat = lat
        settings.weather_lon = lon
        settings.weather_fahrenheit = bool(self._conky_weather_temp_unit.currentData())
        settings.system_stats_style = str(self._conky_system_stats_style.currentData() or "text")
        settings.conky_panel_opacity = max(
            0.0, min(1.0, 1.0 - self._conky_panel_transparency.value() / 100.0)
        )
        settings.conky_theme_id = str(
            self._conky_theme_combo.currentData() or conky_themes.DEFAULT_THEME_ID
        )
        settings.conky_window_mode = str(
            self._conky_window_mode.currentData() or "desktop"
        )
        settings.conky_preset_positions = {
            pid: str(
                self._conky_position_combos[pid].currentData()
                or conky_presets.default_alignment_for_preset(pid)
            )
            for pid in self._conky_position_combos
        }
        settings.autostart_enabled = bool(self._conky_autostart_check.isChecked())
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
        self._persist_autostart_running()

    def _conky_stop_preset(self, preset_id: str) -> None:
        ok, msg = conky_presets.stop_preset(preset_id)
        self._append_log(f"Conky [{preset_id}]: {msg}")
        if not ok:
            QMessageBox.warning(self, "Conky", msg)
        self._refresh_conky_status_labels()
        self._persist_autostart_running()

    def _conky_stop_all_clicked(self) -> None:
        conky_presets.stop_all_presets()
        self._append_log("Conky: stopped all bundled presets.")
        self._refresh_conky_status_labels()
        self._persist_autostart_running()

    def _conky_recover_desktop_clicked(self) -> None:
        from plasmacolorizer.conky.recover import recover_desktop

        reply = QMessageBox.question(
            self,
            "Recover Plasma desktop",
            "Stop all Conky panels, disable Conky login autostart, stop the "
            "wallpaper daemon, and restart plasmashell if it is missing?\n\n"
            "Colour schemes are not changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        notes = recover_desktop()
        for line in notes:
            self._append_log(f"Recover: {line}")
        self._refresh_conky_status_labels()
        self._conky_autostart_check.blockSignals(True)
        self._conky_autostart_check.setChecked(False)
        self._conky_autostart_check.blockSignals(False)
        QMessageBox.information(
            self,
            "Recover Plasma desktop",
            "Recovery finished:\n\n" + "\n".join(notes),
        )

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
        self._persist_autostart_running()

    def _persist_autostart_running(self) -> None:
        """Snapshot which bundled presets are running and update settings + autostart entry."""
        try:
            settings = load_conky_settings()
        except OSError as exc:
            self._append_log(f"Autostart: could not load settings: {exc}")
            return
        running = [pid for pid in conky_presets.PRESETS if conky_presets.is_preset_running(pid)]
        if list(settings.autostart_preset_ids) != running:
            settings.autostart_preset_ids = running
            try:
                save_conky_settings(settings)
            except OSError as exc:
                self._append_log(f"Autostart: could not save running set: {exc}")
                return
        if settings.autostart_enabled and not conky_presets.autostart_entry_installed():
            try:
                conky_presets.install_autostart_entry()
            except OSError as exc:
                self._append_log(f"Autostart: could not install entry: {exc}")

    def _on_conky_autostart_toggled(self, checked: bool) -> None:
        try:
            settings = load_conky_settings()
            settings.autostart_enabled = bool(checked)
            save_conky_settings(settings)
        except OSError as exc:
            self._append_log(f"Autostart: could not save settings: {exc}")
            return
        if checked:
            try:
                path = conky_presets.install_autostart_entry()
                self._append_log(f"Autostart enabled: wrote {path}")
            except OSError as exc:
                self._append_log(f"Autostart: could not install entry: {exc}")
        else:
            removed = conky_presets.uninstall_autostart_entry()
            self._append_log(
                "Autostart disabled" + (" (removed entry)" if removed else "")
            )

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
