"""Resolve the current Plasma wallpaper image path."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".jxl"}

PLASMA_SERVICE = "org.kde.plasmashell"
PLASMA_PATH = "/PlasmaShell"
PLASMA_IFACE = "org.kde.PlasmaShell"


def _dbus_session_interface():
    import dbus  # local import so import fails clearly when dbus-python missing

    bus = dbus.SessionBus()
    obj = bus.get_object(PLASMA_SERVICE, PLASMA_PATH)
    return dbus.Interface(obj, PLASMA_IFACE)


def _strip_file_scheme(val: str) -> str:
    s = val.strip()
    if s.startswith("file://"):
        s = s[7:]
    return s.replace("%20", " ")


def _collect_images_under(dir_path: str, max_depth: int = 4) -> list[str]:
    """Collect image files under a wallpaper package folder (non-recursive first, then shallow walk)."""
    if not os.path.isdir(dir_path):
        return []
    base_depth = dir_path.rstrip(os.sep).count(os.sep)
    out: list[str] = []
    for root, dirs, files in os.walk(dir_path):
        depth = root.count(os.sep) - base_depth
        if depth > max_depth:
            dirs.clear()
            continue
        for name in files:
            if os.path.splitext(name)[1].lower() in _IMAGE_EXTS:
                out.append(os.path.join(root, name))
    return out


def _pick_representative_image(paths: list[str]) -> str | None:
    """Prefer a small landscape file (similar intent to kde-material-you-colors)."""
    if not paths:
        return None
    paths = sorted(paths, key=os.path.getsize)
    try:
        from PIL import Image  # type: ignore[import-untyped]

        landscape: list[str] = []
        portrait: list[str] = []
        for path in paths:
            try:
                with Image.open(path) as im:
                    w, h = im.size
            except OSError:
                continue
            (landscape if w >= h else portrait).append(path)
        if landscape:
            return landscape[0]
        if portrait:
            return portrait[0]
    except ImportError:
        pass
    return paths[0]


def _path_from_plasma_wallpaper_package_dir(root: str, prefer_light: bool) -> str | None:
    """
    KDE often stores `Image` as a *directory* (wallpaper package), not a single file.
    Resolve to an image under contents/images or contents/images_dark.
    """
    root = os.path.abspath(root.rstrip(os.sep))
    dark = os.path.join(root, "contents", "images_dark")
    normal = os.path.join(root, "contents", "images")
    chosen: str | None = None
    if prefer_light:
        if os.path.isdir(normal):
            chosen = normal
        elif os.path.isdir(dark):
            chosen = dark
    else:
        if os.path.isdir(dark):
            chosen = dark
        elif os.path.isdir(normal):
            chosen = normal
    if chosen is None:
        return None
    candidates = _collect_images_under(chosen)
    picked = _pick_representative_image(candidates)
    return os.path.abspath(picked) if picked else None


def _resolve_wallpaper_path_candidate(raw: Any, prefer_light: bool) -> str | None:
    """Resolve DBus / script `Image` value to a readable image file (file or wallpaper package dir)."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    s = _strip_file_scheme(str(raw))
    if not s:
        return None
    if os.path.isfile(s):
        return os.path.abspath(s)
    if os.path.isdir(s):
        return _path_from_plasma_wallpaper_package_dir(s, prefer_light)
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
    for key in ("Image", "image"):
        path = _resolve_wallpaper_path_candidate(wcfg.get(key), prefer_light)
        if path:
            return path
    slide = wcfg.get("SlidePaths") or wcfg.get("slidePaths")
    if slide:
        seq = slide if isinstance(slide, (list, tuple)) else [slide]
        for item in seq:
            p = _resolve_wallpaper_path_candidate(item, prefer_light)
            if p:
                return p
    return None


# __PC_MON__ is replaced with the integer screen index (Plasma desktop.screen).
_EVAL_SCRIPT_TEMPLATE = r"""
(function () {
  var target = __PC_MON__;
  function collect(desks, useScreenFilter) {
    var lines = [];
    for (var i = 0; i < desks.length; i++) {
      var d = desks[i];
      if (useScreenFilter && typeof target === "number" && target >= 0
          && typeof d.screen !== "undefined" && d.screen !== target) {
        continue;
      }
      var plugin = d.wallpaperPlugin;
      if (!plugin) { continue; }
      d.currentConfigGroup = ["Wallpaper", plugin, "General"];
      var img = d.readConfig("Image");
      if (img && String(img).length) {
        lines.push(String(img));
      }
    }
    return lines;
  }
  var desks = desktops();
  if (!desks.length) {
    return "ERROR:no_desktops";
  }
  var lines = collect(desks, true);
  if (!lines.length) {
    lines = collect(desks, false);
  }
  if (!lines.length) {
    return "ERROR:no_images";
  }
  return lines[0];
})();
"""


def _wallpaper_via_evaluate_script(monitor: int, prefer_light: bool) -> str | None:
    try:
        iface = _dbus_session_interface()
        script = _EVAL_SCRIPT_TEMPLATE.replace("__PC_MON__", str(int(monitor)))
        out = iface.evaluateScript(script)
    except Exception as exc:  # noqa: BLE001
        logger.debug("evaluateScript failed: %s", exc)
        return None
    if out is None:
        return None
    text = out.decode("utf-8") if isinstance(out, (bytes, bytearray)) else str(out)
    text = text.strip().strip('"').replace("%20", " ")
    if text.startswith("ERROR:"):
        return None
    return _resolve_wallpaper_path_candidate(text, prefer_light)


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

    path = _wallpaper_via_evaluate_script(monitor, prefer_light)
    if path:
        return path

    _wallpaper_via_qdbus(monitor)  # best-effort log path
    raise FileNotFoundError(
        "Could not resolve wallpaper image. "
        "Use the Image wallpaper (org.kde.image), a bundled wallpaper package, "
        "or set Override to an image file."
    )
