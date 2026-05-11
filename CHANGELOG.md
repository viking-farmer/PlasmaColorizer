# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- File-based logger at `~/.cache/plasmacolorizer/log.txt` with timestamps,
  PID, and thread IDs. Visible to the user from the in-app log too.
- `CHANGELOG.md` and conventional-commit policy.
- Optional **Restart Plasma shell** checkbox (on by default): runs
  ``kquitapp6 plasmashell`` then ``kstart plasmashell`` so the task bar and
  Kickoff fully reload cached colors.
- After applying a palette, call **``org.kde.plasmashell.accentColor``**
  ``setAccentColor`` so the global Plasma accent (used heavily by the panel
  and launcher) matches the Material primary colour.
- Install a **Plasma desktop theme** under
  ``~/.local/share/plasma/desktoptheme/PlasmaColorizer/`` (``colors`` +
  ``metadata.json`` + ``plasmarc`` with ``FallbackTheme``) and set
  ``~/.config/plasmarc`` ``[Theme] name=PlasmaColorizer``, because the task bar
  and Kickoff read shell colours from the active **Plasma Style**, not only from
  ``kdeglobals``.

### Changed
- The DBus session is now only touched from the GUI thread.  Wallpaper
  detection and the post-apply notification both happen on the main
  thread; the background worker performs only deterministic CPU work
  (quantizer, palette, file writes).  This avoids deadlocks observed
  when calling `dbus-python` from arbitrary Python threads.
- `GenerateSchemeWorker` now takes an already-resolved `src_path` and
  reports each step over a `progress` signal.
- The busy indicator dialog is non-modal so the in-app log remains
  responsive while work is in progress.

### Fixed
- Plasma 6: session bus has no ``org.kde.KGlobalSettings`` (always
  ``ServiceUnknown``).  Palette refresh now calls ``org.kde.KWin.reconfigure``
  and ``org.kde.PlasmaShell.refreshCurrentShell`` instead.
- When ``[General]`` had ``accentColorFromWallpaper=true``, Plasma kept
  overriding accent colors from the wallpaper so the generated scheme looked
  unchanged.  We now set ``accentColorFromWallpaper=false``, sync
  ``AccentColor`` to the Material primary, and update ``ColorSchemeHash`` to
  the SHA-1 of the written ``.colors`` file.
- Progress log lines were duplicated (worker + GUI both logged the same
  message); worker progress now only emits the signal.
- Generate and apply no longer hangs on systems where Plasma's DBus
  reply for `plasma-apply-colorscheme` is delayed.  We bypass that
  command entirely and write `~/.config/kdeglobals` directly, which is
  what `plasma-apply-colorscheme` does internally.
- The background worker now actually runs.  The QThread / worker
  objects were stored only in local variables in `_on_generate`, so
  Python garbage-collected the worker before the thread's event loop
  could call `worker.run()`.  We now keep strong references on the
  `MainWindow` and parent the QThread to it.
- The application now exits cleanly when its window is closed.  An
  explicit `closeEvent` quits any still-running worker thread (3 s
  grace period, then terminate), so the process no longer has to be
  killed manually.

## [0.1.0] - 2026-05-10

### Added
- Initial release.
- Detect wallpaper via `org.kde.PlasmaShell` (DBus).
- Material You palette extraction via `materialyoucolor`.
- Optional green-accent hue bias.
- Write Plasma color scheme to
  `~/.local/share/color-schemes/PlasmaColorizer.colors`.
- Conky template tab with `{{token}}` rendering.
- Launcher script (`run.sh`) and KDE `.desktop` entry.
