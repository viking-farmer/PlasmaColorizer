"""Background wallpaper watcher — auto re-apply when the Plasma wallpaper changes.

Replaces the kde-material-you-colors polling loop.  Run at login via
``~/.config/autostart/plasmacolorizer-daemon.desktop`` or manually:

    plasmacolorizer-daemon --foreground
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import time
from pathlib import Path

from plasmacolorizer.core.apply_pipeline import generate_and_apply_from_wallpaper
from plasmacolorizer.core.app_settings import AppSettings, load_app_settings
from plasmacolorizer.core.logger import get_logger
from plasmacolorizer.core.wallpaper_watch import (
    WALLPAPER_CHANGE_DEBOUNCE_MS,
    wallpaper_fingerprint,
)

PID_DIR_NAME = ".cache/plasmacolorizer"
AUTOSTART_DIR_NAME = ".config/autostart"
AUTOSTART_FILE = "plasmacolorizer-daemon.desktop"
_STOP = False


def pid_dir() -> Path:
    return Path(os.path.expanduser(f"~/{PID_DIR_NAME}"))


def pid_file_path() -> Path:
    return pid_dir() / "daemon.pid"


def autostart_dir() -> Path:
    return Path(os.path.expanduser(f"~/{AUTOSTART_DIR_NAME}"))


def is_daemon_running() -> bool:
    path = pid_file_path()
    if not path.is_file():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_daemon() -> bool:
    path = pid_file_path()
    if not path.is_file():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        path.unlink(missing_ok=True)
        return False
    return True


def _write_pid() -> None:
    pid_dir().mkdir(parents=True, exist_ok=True)
    pid_file_path().write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid() -> None:
    pid_file_path().unlink(missing_ok=True)


def autostart_desktop_path() -> Path:
    return autostart_dir() / AUTOSTART_FILE


def resolve_daemon_executable() -> str:
    """Return ``plasmacolorizer-daemon`` on PATH, or the script next to ``sys.executable``."""
    found = shutil.which("plasmacolorizer-daemon")
    if found:
        return found
    candidate = Path(sys.executable).resolve().parent / "plasmacolorizer-daemon"
    if candidate.is_file():
        return str(candidate)
    return f"{sys.executable} -m plasmacolorizer.wallpaper_daemon"


def autostart_desktop_contents() -> str:
    exe = resolve_daemon_executable()
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=PlasmaColorizer wallpaper watcher\n"
        "Comment=Re-apply Material You colors when the Plasma wallpaper changes\n"
        f"Exec={exe}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-phase=2\n"
        "X-KDE-autostart-after=panel\n"
    )


def install_autostart() -> Path:
    """Write (or refresh) the autostart ``.desktop`` file. Returns its path."""
    path = autostart_desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(autostart_desktop_contents(), encoding="utf-8")
    return path


def uninstall_autostart() -> bool:
    path = autostart_desktop_path()
    if not path.is_file():
        return False
    path.unlink()
    return True


def autostart_installed() -> bool:
    return autostart_desktop_path().is_file()


def _handle_stop(signum: int, _frame) -> None:  # noqa: ANN001
    del signum
    global _STOP
    _STOP = True


def run_loop(app: AppSettings | None = None) -> int:
    log = get_logger()
    settings = app or load_app_settings()
    log.info(
        "PlasmaColorizer wallpaper daemon started (monitor=%s, poll=%ss)",
        settings.wallpaper_monitor,
        settings.wallpaper_daemon_poll_interval_s,
    )
    pending_fp: str | None = None
    pending_since: float | None = None
    debounce_s = WALLPAPER_CHANGE_DEBOUNCE_MS / 1000.0
    interval = max(1.0, float(settings.wallpaper_daemon_poll_interval_s))
    null_fp_streak = 0

    while not _STOP:
        settings = load_app_settings()
        if not settings.wallpaper_daemon_enabled:
            time.sleep(interval)
            continue
        if not settings.auto_apply_on_wallpaper_change:
            time.sleep(interval)
            continue

        fp = wallpaper_fingerprint(settings.wallpaper_monitor)
        now = time.monotonic()
        if fp is None:
            null_fp_streak += 1
            # Back off while plasmashell is down so we do not spam DBus every 3s.
            backoff = min(60.0, interval * (2 ** min((null_fp_streak - 1) // 5, 4)))
            if null_fp_streak == 1 or null_fp_streak % 10 == 0:
                log.warning(
                    "[daemon] cannot resolve wallpaper (DBus/plasmashell unavailable?) — "
                    "retrying in %.0fs",
                    backoff,
                )
            time.sleep(backoff)
            continue
        null_fp_streak = 0

        applied = settings.last_applied_wallpaper_fingerprint
        if fp == applied:
            pending_fp = None
            pending_since = None
            time.sleep(interval)
            continue

        if pending_fp != fp:
            pending_fp = fp
            pending_since = now
            if applied:
                log.info(
                    "[daemon] wallpaper changed; debouncing %.1fs before apply",
                    debounce_s,
                )
            else:
                log.info(
                    "[daemon] no prior apply recorded for current wallpaper; "
                    "debouncing %.1fs before first apply",
                    debounce_s,
                )
        elif pending_since is not None and (now - pending_since) >= debounce_s:
            try:
                log.info("[daemon] auto-applying palette")
                result = generate_and_apply_from_wallpaper(
                    app_settings=settings,
                    log_prefix="[daemon]",
                )
                if not result.disk.apply_ok:
                    log.warning("[daemon] apply failed: %s", result.disk.apply_error)
                else:
                    log.info(
                        "[daemon] applied %s; notify=%s; plasma_restart=%s",
                        result.src,
                        result.notify_msg,
                        result.restart_msg or "skipped",
                    )
            except Exception as exc:  # noqa: BLE001
                log.exception("[daemon] auto-apply failed: %s", exc)
            pending_fp = None
            pending_since = None

        time.sleep(interval)

    log.info("PlasmaColorizer wallpaper daemon stopping")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plasmacolorizer-daemon",
        description="Watch the Plasma wallpaper and re-apply PlasmaColorizer themes.",
    )
    parser.add_argument(
        "--foreground",
        "-f",
        action="store_true",
        help="Run in the foreground (default when not already daemonized).",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop a running wallpaper daemon and exit.",
    )
    parser.add_argument(
        "--install-autostart",
        action="store_true",
        help="Install ~/.config/autostart/plasmacolorizer-daemon.desktop",
    )
    parser.add_argument(
        "--uninstall-autostart",
        action="store_true",
        help="Remove the login autostart entry.",
    )
    args = parser.parse_args(argv)

    if args.install_autostart:
        path = install_autostart()
        sys.stdout.write(f"Installed autostart: {path}\n")
        return 0
    if args.uninstall_autostart:
        removed = uninstall_autostart()
        sys.stdout.write(
            "Removed autostart entry.\n" if removed else "Autostart entry was not installed.\n",
        )
        return 0
    if args.stop:
        stopped = stop_daemon()
        sys.stdout.write(
            "Stopped wallpaper daemon.\n" if stopped else "No running wallpaper daemon found.\n",
        )
        return 0

    if is_daemon_running() and not args.foreground:
        sys.stderr.write("PlasmaColorizer wallpaper daemon is already running.\n")
        return 1

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    _write_pid()
    try:
        return run_loop()
    finally:
        _remove_pid()


if __name__ == "__main__":
    raise SystemExit(main())
