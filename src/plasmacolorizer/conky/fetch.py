"""CLI for Conky `execi`: ESV passage text and Open-Meteo weather (stdlib urllib)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from plasmacolorizer.conky.settings_store import ConkySettings, load_conky_settings

# Short references rotated by calendar day (ESV API passage/text).
_DAILY_PASSAGES: tuple[str, ...] = (
    "John 3:16",
    "Psalm 23:1-4",
    "Philippians 4:6-7",
    "Romans 8:28",
    "Isaiah 40:31",
    "Matthew 11:28-30",
    "Proverbs 3:5-6",
    "Jeremiah 29:11",
    "Joshua 1:9",
    "Psalm 119:105",
    "Romans 12:2",
    "Galatians 5:22-23",
    "Ephesians 2:8-9",
    "Colossians 3:23",
    "Hebrews 11:1",
    "James 1:5",
    "1 Peter 5:7",
    "1 John 4:19",
    "Psalm 46:10",
    "Micah 6:8",
    "Luke 6:31",
    "Mark 12:30-31",
    "Genesis 1:1",
    "Exodus 20:12",
    "Deuteronomy 31:6",
    "Nehemiah 8:10",
    "Psalm 27:1",
    "Psalm 37:4",
    "Isaiah 41:10",
    "Matthew 5:9",
    "Matthew 6:33",
    "John 14:27",
    "John 15:5",
    "Acts 1:8",
    "Romans 5:8",
    "Romans 15:13",
    "1 Corinthians 13:4-5",
    "2 Timothy 1:7",
    "Hebrews 13:5",
    "Revelation 21:4",
)

_WMO_LABEL: dict[int, str] = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog",
    51: "Drizzle",
    53: "Drizzle",
    55: "Drizzle",
    61: "Rain",
    63: "Rain",
    65: "Rain",
    71: "Snow",
    73: "Snow",
    75: "Snow",
    80: "Showers",
    81: "Showers",
    82: "Showers",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


def _http_get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> object:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _http_get_text(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_esv_line() -> str:
    settings = load_conky_settings()
    key = (settings.esv_api_key or "").strip()
    if not key:
        return "Set ESV API key in PlasmaColorizer → Conky settings."

    yday = datetime.now(timezone.utc).timetuple().tm_yday
    q = _DAILY_PASSAGES[(yday - 1) % len(_DAILY_PASSAGES)]
    url = "https://api.esv.org/v3/passage/text/?" + urllib.parse.urlencode(
        {"q": q, "include-headings": "false"}
    )
    try:
        data = _http_get_json(
            url,
            headers={"Authorization": f"Token {key}"},
        )
    except urllib.error.HTTPError as exc:
        return f"ESV HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return f"ESV error: {exc}"

    if not isinstance(data, dict):
        return "ESV: bad response"
    passages = data.get("passages")
    if not passages or not isinstance(passages, list):
        return "ESV: no passage"
    text = passages[0] if passages else ""
    if not isinstance(text, str):
        return "ESV: bad passage"
    one = " ".join(text.split())
    if len(one) > 220:
        one = one[:217] + "…"
    return one


def _geocode_city(city: str) -> tuple[float, float] | None:
    city = city.strip()
    if not city:
        return None
    q = urllib.parse.urlencode({"name": city, "count": "1", "language": "en", "format": "json"})
    url = f"https://geocoding-api.open-meteo.com/v1/search?{q}"
    try:
        data = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if not results or not isinstance(results, list):
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    lat, lon = first.get("latitude"), first.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _resolve_lat_lon(settings: ConkySettings) -> tuple[float, float] | None:
    if settings.weather_lat is not None and settings.weather_lon is not None:
        return float(settings.weather_lat), float(settings.weather_lon)
    return _geocode_city(settings.weather_city)


def fetch_weather_line() -> str:
    settings = load_conky_settings()
    coords = _resolve_lat_lon(settings)
    if coords is None:
        return "Set city or lat/lon in PlasmaColorizer → Conky."
    lat, lon = coords
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code",
            "timezone": "auto",
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    try:
        data = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return f"Weather: {exc}"

    if not isinstance(data, dict):
        return "Weather: bad response"
    cur = data.get("current")
    if not isinstance(cur, dict):
        return "Weather: no current"
    temp = cur.get("temperature_2m")
    code = cur.get("weather_code")
    label = _WMO_LABEL.get(int(code), "—") if code is not None else "—"
    try:
        t = float(temp) if temp is not None else float("nan")
    except (TypeError, ValueError):
        t = float("nan")
    if t != t:  # NaN
        return f"{label}"
    return f"{t:.0f}°C  {label}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="plasmacolorizer.conky.fetch")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("esv", help="Print one-line ESV passage for Conky")
    sub.add_parser("weather", help="Print one-line Open-Meteo summary for Conky")

    args = p.parse_args(argv)
    if args.cmd == "esv":
        sys.stdout.write(fetch_esv_line() + "\n")
        return 0
    if args.cmd == "weather":
        sys.stdout.write(fetch_weather_line() + "\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
