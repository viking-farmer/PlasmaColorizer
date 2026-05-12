"""CLI for Conky `execi`: ESV passage text and Open-Meteo weather (stdlib urllib)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from plasmacolorizer.conky.settings_store import load_conky_settings

# Open-Meteo asks for a descriptive User-Agent; bare urllib defaults may get empty responses.
_DEFAULT_UA = (
    "PlasmaColorizer/0.1 (+https://github.com/viking-farmer/PlasmaColorizer; conky weather)"
)

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

@dataclass(frozen=True)
class GeocodeHit:
    """One row from Open-Meteo's geocoding API (or a bundled preset)."""

    label: str
    latitude: float
    longitude: float


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

# WMO weather codes → emoji (https://open-meteo.com/en/docs)
_WMO_EMOJI: dict[int, str] = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    48: "🌫️",
    51: "🌦️",
    53: "🌦️",
    55: "🌦️",
    61: "🌧️",
    63: "🌧️",
    65: "🌧️",
    71: "❄️",
    73: "❄️",
    75: "❄️",
    80: "🌧️",
    81: "🌧️",
    82: "🌧️",
    95: "⛈️",
    96: "⛈️",
    99: "⛈️",
}


def _weather_emoji(code_i: int | None) -> str:
    if code_i is None:
        return "🌡️"
    return _WMO_EMOJI.get(code_i, "🌤️")


def _merge_headers(extra: dict[str, str] | None) -> dict[str, str]:
    h = {"User-Agent": _DEFAULT_UA}
    if extra:
        h.update(extra)
    return h


def _http_get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> object:
    req = urllib.request.Request(url, headers=_merge_headers(headers))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _http_get_text(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers=_merge_headers(headers))
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


def _format_geocode_row(row: dict) -> str:
    name = row.get("name")
    if not name:
        return "?"
    country = row.get("country") or ""
    admin1 = row.get("admin1") or ""
    tail_bits = [x for x in (admin1, country) if x]
    tail = ", ".join(tail_bits)
    return f"{name}, {tail}" if tail else str(name)


def geocode_search(query: str, *, limit: int = 15) -> list[GeocodeHit]:
    """Search locations via ``https://geocoding-api.open-meteo.com`` (same index the site uses)."""
    query = query.strip()
    if not query:
        return []
    q = urllib.parse.urlencode(
        {"name": query, "count": str(limit), "language": "en", "format": "json"}
    )
    url = f"https://geocoding-api.open-meteo.com/v1/search?{q}"
    try:
        data = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict) or data.get("error") is True:
        return []
    results = data.get("results")
    if not results or not isinstance(results, list):
        return []
    out: list[GeocodeHit] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        lat, lon = row.get("latitude"), row.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            out.append(
                GeocodeHit(
                    label=_format_geocode_row(row),
                    latitude=float(lat),
                    longitude=float(lon),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _geocode_city(city: str) -> tuple[float, float] | None:
    hits = geocode_search(city, limit=10)
    if not hits:
        return None
    h = hits[0]
    return h.latitude, h.longitude


def fetch_weather_line() -> str:
    settings = load_conky_settings()
    city = (settings.weather_city or "").strip()

    if settings.weather_lat is not None and settings.weather_lon is not None:
        lat, lon = float(settings.weather_lat), float(settings.weather_lon)
    elif city:
        coords = _geocode_city(city)
        if coords is None:
            return (
                f'Weather: no match for “{city}”. Save Conky settings, check spelling, '
                "or set lat/lon."
            )
        lat, lon = coords
    else:
        return "Set city or lat/lon in PlasmaColorizer → Conky (then Save)."
    use_f = bool(settings.weather_fahrenheit)
    temp_unit = "fahrenheit" if use_f else "celsius"
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code",
            "timezone": "auto",
            "temperature_unit": temp_unit,
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
    try:
        code_i = int(code) if code is not None and code != "" else None
    except (TypeError, ValueError):
        code_i = None
    label = _WMO_LABEL.get(code_i, "—") if code_i is not None else "—"
    emoji = _weather_emoji(code_i)
    deg = "°F" if use_f else "°C"
    try:
        t = float(temp) if temp is not None else float("nan")
    except (TypeError, ValueError):
        t = float("nan")
    if t != t:  # NaN
        return f"{emoji}  {label}"
    return f"{emoji}  {t:.0f}{deg}  {label}"


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
