"""Resolve the current Plasma wallpaper image path."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

PLASMA_SERVICE = "org.kde.plasmashell"
PLASMA_PATH = "/PlasmaShell"
PLASMA_IFACE = "org.kde.PlasmaShell"


def _dbus_session_interface():
    import dbus  # local import so import fails clearly when dbus-python missing

    bus = dbus.SessionBus()
    obj = bus.get_object(PLASMA_SERVICE, PLASMA_PATH)
    return dbus.Interface(obj, PLASMA_IFACE)


def _normalize_image_value(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, bytes):
        val = val.decode("utf-8", errors="replace")
    s = str(val).strip()
    if not s:
        return None
    if s.startswith("file://"):
        s = s[7:]
    s = s.replace("%20", " ")
    if os.path.isdir(s):
        return None
    if os.path.isfile(s):
        return os.path.abspath(s)
    return None


def _dbus_to_python(obj: Any) -> Any:
    import dbus

    if isinstance(obj, dbus.Dictionary):
        return {str(k): _dbus_to_python(v) for k, v in obj.items()}
    if isinstance(obj, dbus.Array):
        return [_dbus_to_python(v) for v in obj]
    if isinstance(obj, dbus.String):
        return str(obj)
    utf8 = getattr(dbus, "UTF8String", None)
    if utf8 is not None and isinstance(obj, utf8):
        return str(obj)
    if isinstance(obj, dbus.ByteArray):
        return bytes(obj)
    if isinstance(obj, dbus.Boolean):
        return bool(obj)
    int_types = tuple(
        t
        for name in ("Int16", "Int32", "Int64", "UInt16", "UInt32", "UInt64", "Byte")
        if (t := getattr(dbus, name, None)) is not None
    )
    if int_types and isinstance(obj, int_types):
        return int(obj)
    dbl = getattr(dbus, "Double", None)
    if dbl is not None and isinstance(obj, dbl):
        return float(obj)
    return obj


def _wallpaper_via_plasma_api(monitor: int) -> dict[str, Any] | None:
    """Use PlasmaShell.wallpaper(monitor) when available (kde-material-you-colors style)."""
    try:
        iface = _dbus_session_interface()
        if not hasattr(iface, "wallpaper"):
            return None
        out = iface.wallpaper(int(monitor))
    except Exception as exc:  # noqa: BLE001 — DBus surface broad on purpose
        logger.debug("PlasmaShell.wallpaper failed: %s", exc)
        return None
    out = _dbus_to_python(out)
    if isinstance(out, dict):
        return {str(k): v for k, v in out.items()}
    return None


def _path_from_config(wcfg: dict[str, Any], prefer_light: bool) -> str | None:
    """Pick a file path from wallpaper config dict."""
    img = wcfg.get("Image") or wcfg.get("image")
    path = _normalize_image_value(img)
    if path:
        return path
    slide = wcfg.get("SlidePaths") or wcfg.get("slidePaths")
    if slide:
        first = slide[0] if isinstance(slide, (list, tuple)) else slide
        p = _normalize_image_value(first)
        if p:
            return p
    return None


_EVAL_SCRIPT = r"""
(function () {
  const desks = desktops();
  if (!desks.length) {
    return "ERROR:no_desktops";
  }
  const lines = [];
  for (let i = 0; i < desks.length; i++) {
    const d = desks[i];
    var plugin = d.wallpaperPlugin;
    if (!plugin) { continue; }
    d.currentConfigGroup = ['Wallpaper', plugin, 'General'];
    var img = d.readConfig('Image');
    if (img && img.length) {
      lines.push(String(img));
    }
  }
  if (!lines.length) { return "ERROR:no_images"; }
  return lines[0];
})();
"""


def _wallpaper_via_evaluate_script() -> str | None:
    try:
        iface = _dbus_session_interface()
        if not hasattr(iface, "evaluateScript"):
            return None
        out = iface.evaluateScript(_EVAL_SCRIPT)
    except Exception as exc:  # noqa: BLE001
        logger.debug("evaluateScript failed: %s", exc)
        return None
    if out is None:
        return None
    text = out.decode("utf-8") if isinstance(out, (bytes, bytearray)) else str(out)
    text = text.strip().strip('"').replace("%20", " ")
    if text.startswith("ERROR:"):
        return None
    return _normalize_image_value(text)


def _wallpaper_via_qdbus(monitor: int) -> str | None:
    for prog in ("qdbus6", "qdbus"):
        try:
            out = subprocess.check_output(
                [
                    prog,
                    PLASMA_SERVICE,
                    PLASMA_PATH,
                    PLASMA_IFACE,
                    "wallpaper",
                    str(int(monitor)),
                ],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, OSError):
            continue
        # Output may be a repr of dict; fall through to API when possible
        logger.debug("qdbus raw wallpaper: %s", out[:200])
    return None


def current_wallpaper_image_path(monitor: int = 0, prefer_light: bool = False) -> str:
    """
    Return filesystem path to the current wallpaper image.

    Raises FileNotFoundError when the source cannot be resolved.
    """
    wcfg = _wallpaper_via_plasma_api(monitor)
    if wcfg:
        path = _path_from_config(wcfg, prefer_light)
        if path:
            return path
        plugin = str(wcfg.get("wallpaperPlugin") or wcfg.get("WallpaperPlugin") or "")
        logger.info("Wallpaper plugin %s did not yield a file path; trying script API", plugin)

    path = _wallpaper_via_evaluate_script()
    if path:
        return path

    _wallpaper_via_qdbus(monitor)  # best-effort log path
    raise FileNotFoundError(
        "Could not resolve wallpaper image. "
        "Use a static picture wallpaper (org.kde.image) or set a manual path when supported."
    )
