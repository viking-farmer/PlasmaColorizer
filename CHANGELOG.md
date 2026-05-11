# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- File-based logger at `~/.cache/plasmacolorizer/log.txt` with timestamps,
  PID, and thread IDs. Visible to the user from the in-app log too.
- `CHANGELOG.md` and conventional-commit policy.

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
- Generate and apply no longer hangs on systems where Plasma's DBus
  reply for `plasma-apply-colorscheme` is delayed.  We bypass that
  command entirely and write `~/.config/kdeglobals` directly, which is
  what `plasma-apply-colorscheme` does internally.

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
