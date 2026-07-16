"""Emergency recovery when Conky / PlasmaColorizer leave plasmashell dead.

Typical failure mode on Plasma Wayland: several XWayland Conky windows with
``own_window_type = normal`` + ARGB / opacity hints stress KWin or leave
``plasmashell`` dead after a theme apply that also restarts the shell.

Safe recovery order (never touches colour schemes or ``kdeglobals``):

1. Stop every Conky we started (and any leftover ``conky`` processes).
2. Optionally disable Conky login autostart so the next login does not
   immediately respawn the same panels.
3. Stop the wallpaper daemon (it otherwise hammers DBus while plasmashell is down).
4. Start ``plasmashell`` again if it is missing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import time

from plasmacolorizer.conky import presets as conky_presets


def stop_all_conky(*, aggressive: bool = True) -> list[str]:
    """Stop bundled presets and, if ``aggressive``, any remaining ``conky`` PIDs."""
    notes: list[str] = []
    conky_presets.stop_all_presets()
    notes.append("stopped bundled PlasmaColorizer Conky presets")
    # Clear stale pid files even if processes were already gone.
    cache = conky_presets.conky_cache_dir()
    if cache.is_dir():
        for pf in cache.glob("*.pid"):
            try:
                pf.unlink()
            except OSError:
                pass
    if aggressive and shutil.which("pkill"):
        try:
            subprocess.run(["pkill", "-x", "conky"], check=False, timeout=4)
            notes.append("pkill -x conky")
        except (OSError, subprocess.SubprocessError) as exc:
            notes.append(f"pkill conky failed: {exc}")
    return notes


def disable_conky_autostart() -> str:
    """Rename the Conky autostart ``.desktop`` so login will not respawn panels."""
    path = conky_presets.autostart_desktop_path()
    disabled = path.with_suffix(path.suffix + ".disabled")
    if not path.is_file():
        if disabled.is_file():
            return f"already disabled: {disabled}"
        return "no Conky autostart entry present"
    try:
        os.replace(path, disabled)
    except OSError as exc:
        return f"could not disable Conky autostart: {exc}"
    return f"disabled Conky autostart → {disabled}"


def enable_conky_autostart() -> str:
    """Restore a previously disabled Conky autostart entry (if present)."""
    path = conky_presets.autostart_desktop_path()
    disabled = path.with_suffix(path.suffix + ".disabled")
    if path.is_file():
        return f"already enabled: {path}"
    if not disabled.is_file():
        return "no disabled Conky autostart entry to restore"
    try:
        os.replace(disabled, path)
    except OSError as exc:
        return f"could not re-enable Conky autostart: {exc}"
    return f"re-enabled Conky autostart → {path}"


def stop_wallpaper_daemon() -> str:
    """Stop the background wallpaper watcher (best-effort)."""
    from plasmacolorizer import wallpaper_daemon

    pid_path = wallpaper_daemon.pid_file_path()
    killed = False
    if pid_path.is_file():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGTERM)
            killed = True
        except (OSError, ValueError):
            pass
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
    if shutil.which("pkill"):
        try:
            subprocess.run(
                ["pkill", "-f", "plasmacolorizer.wallpaper_daemon"],
                check=False,
                timeout=4,
            )
            killed = True
        except (OSError, subprocess.SubprocessError):
            pass
    return "stopped wallpaper daemon" if killed else "wallpaper daemon was not running"


def plasmashell_running() -> bool:
    try:
        r = subprocess.run(
            ["pgrep", "-x", "plasmashell"],
            check=False,
            capture_output=True,
            timeout=3,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_plasmashell(*, wait_s: float = 8.0) -> tuple[bool, str]:
    """Start plasmashell if missing; wait briefly for it to come up."""
    if plasmashell_running():
        return True, "plasmashell already running"

    kstart = shutil.which("kstart")
    shell = shutil.which("plasmashell")
    if kstart:
        cmd = [kstart, "plasmashell"]
    elif shell:
        cmd = [shell]
    else:
        return False, "neither kstart nor plasmashell found in PATH"

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return False, f"failed to start plasmashell: {exc}"

    deadline = time.monotonic() + max(1.0, wait_s)
    while time.monotonic() < deadline:
        if plasmashell_running():
            return True, f"started plasmashell via {cmd[0]}"
        time.sleep(0.25)
    return False, (
        f"launched {cmd[0]} but plasmashell did not appear within {wait_s:.0f}s — "
        "try logging out/in, or run: kstart plasmashell"
    )


def recover_desktop(
    *,
    disable_autostart: bool = True,
    stop_daemon: bool = True,
    start_shell: bool = True,
) -> list[str]:
    """Run the full safe recovery sequence. Returns human-readable step notes."""
    notes: list[str] = []
    notes.extend(stop_all_conky(aggressive=True))
    if disable_autostart:
        notes.append(disable_conky_autostart())
    if stop_daemon:
        notes.append(stop_wallpaper_daemon())
    if start_shell:
        ok, msg = ensure_plasmashell()
        notes.append(("OK: " if ok else "WARN: ") + msg)
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recover a broken Plasma desktop after PlasmaColorizer Conky panels "
            "(stops Conky, optionally disables Conky autostart, restarts plasmashell)."
        )
    )
    parser.add_argument(
        "--keep-autostart",
        action="store_true",
        help="Do not disable ~/.config/autostart/plasmacolorizer-conky.desktop",
    )
    parser.add_argument(
        "--keep-daemon",
        action="store_true",
        help="Leave the wallpaper watcher running",
    )
    parser.add_argument(
        "--no-plasmashell",
        action="store_true",
        help="Only stop Conky/daemon; do not start plasmashell",
    )
    parser.add_argument(
        "--reenable-autostart",
        action="store_true",
        help="Restore a previously disabled Conky autostart entry and exit",
    )
    args = parser.parse_args(argv)

    if args.reenable_autostart:
        print(enable_conky_autostart())
        return 0

    notes = recover_desktop(
        disable_autostart=not args.keep_autostart,
        stop_daemon=not args.keep_daemon,
        start_shell=not args.no_plasmashell,
    )
    for line in notes:
        print(line)
    return 0 if plasmashell_running() or args.no_plasmashell else 1


if __name__ == "__main__":
    raise SystemExit(main())
