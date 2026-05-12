"""Conky fetch helpers (no live network)."""

from __future__ import annotations

from unittest.mock import patch

from plasmacolorizer.conky import fetch
from plasmacolorizer.conky.fetch import GeocodeHit
from plasmacolorizer.conky.settings_store import ConkySettings


def test_fetch_esv_line_without_key() -> None:
    with patch("plasmacolorizer.conky.fetch.load_conky_settings", return_value=ConkySettings()):
        line = fetch.fetch_esv_line()
    assert "key" in line.lower() or "Set ESV" in line


def test_fetch_esv_line_success() -> None:
    settings = ConkySettings(esv_api_key="fake-token")
    payload = {"passages": ["  John 3:16 For God so loved…  "]}

    def fake_json(url, headers=None, timeout=20.0):
        assert "api.esv.org" in url
        assert headers and "Token fake-token" in headers.get("Authorization", "")
        return payload

    with patch("plasmacolorizer.conky.fetch.load_conky_settings", return_value=settings):
        with patch("plasmacolorizer.conky.fetch._http_get_json", side_effect=fake_json):
            line = fetch.fetch_esv_line()
    assert "God" in line or "John" in line


def test_fetch_weather_line_no_location() -> None:
    with patch("plasmacolorizer.conky.fetch.load_conky_settings", return_value=ConkySettings()):
        line = fetch.fetch_weather_line()
    assert "city" in line.lower() or "lat" in line.lower()


def test_fetch_weather_line_success() -> None:
    settings = ConkySettings(weather_lat=52.5, weather_lon=13.4)
    api = {
        "current": {
            "temperature_2m": 12.3,
            "weather_code": 3,
        }
    }

    def fake_json(url, headers=None, timeout=20.0):
        assert "api.open-meteo.com" in url
        return api

    with patch("plasmacolorizer.conky.fetch.load_conky_settings", return_value=settings):
        with patch("plasmacolorizer.conky.fetch._http_get_json", side_effect=fake_json):
            line = fetch.fetch_weather_line()
    assert "12" in line
    assert "Overcast" in line
    assert "°C" in line
    assert "☁️" in line


def test_fetch_weather_line_fahrenheit() -> None:
    settings = ConkySettings(weather_lat=40.0, weather_lon=-74.0, weather_fahrenheit=True)
    api = {"current": {"temperature_2m": 72.0, "weather_code": 0}}

    def fake_json(url, headers=None, timeout=20.0):
        assert "api.open-meteo.com" in url
        assert "temperature_unit=fahrenheit" in url
        return api

    with patch("plasmacolorizer.conky.fetch.load_conky_settings", return_value=settings):
        with patch("plasmacolorizer.conky.fetch._http_get_json", side_effect=fake_json):
            line = fetch.fetch_weather_line()
    assert "72" in line
    assert "°F" in line
    assert "☀️" in line


def test_fetch_weather_line_by_city_geocodes_then_forecast() -> None:
    settings = ConkySettings(weather_city="Seattle")
    geo = {"results": [{"latitude": 52.5, "longitude": 13.4}]}
    api = {"current": {"temperature_2m": 5.0, "weather_code": 0}}

    urls: list[str] = []

    def fake_json(url, headers=None, timeout=20.0):
        urls.append(url)
        if "geocoding-api.open-meteo.com" in url:
            return geo
        if "api.open-meteo.com" in url:
            return api
        raise AssertionError(url)

    with patch("plasmacolorizer.conky.fetch.load_conky_settings", return_value=settings):
        with patch("plasmacolorizer.conky.fetch._http_get_json", side_effect=fake_json):
            line = fetch.fetch_weather_line()
    assert len(urls) == 2
    assert "geocoding-api" in urls[0]
    assert "api.open-meteo.com" in urls[1]
    assert "5" in line
    assert "Clear" in line
    assert "°C" in line
    assert "☀️" in line


def test_fetch_weather_line_city_geocode_miss() -> None:
    settings = ConkySettings(weather_city="XyzzyUnknown123")
    with patch("plasmacolorizer.conky.fetch.load_conky_settings", return_value=settings):
        with patch("plasmacolorizer.conky.fetch._http_get_json", return_value={}):
            line = fetch.fetch_weather_line()
    assert "no match" in line.lower()
    assert "XyzzyUnknown123" in line


def test_merge_headers_adds_user_agent() -> None:
    assert "PlasmaColorizer" in fetch._merge_headers(None)["User-Agent"]
    merged = fetch._merge_headers({"Authorization": "Token x"})
    assert merged["Authorization"] == "Token x"
    assert "User-Agent" in merged


def test_geocode_search_multiple_hits() -> None:
    sample = {
        "results": [
            {"name": "Springfield", "admin1": "Illinois", "country": "United States", "latitude": 39.8, "longitude": -89.6},
            {"name": "Springfield", "admin1": "Missouri", "country": "United States", "latitude": 37.2, "longitude": -93.3},
        ]
    }

    def fake_json(url, headers=None, timeout=20.0):
        assert "geocoding-api" in url
        return sample

    with patch("plasmacolorizer.conky.fetch._http_get_json", side_effect=fake_json):
        hits = fetch.geocode_search("Springfield", limit=5)
    assert len(hits) == 2
    assert hits[0].label.startswith("Springfield")
    assert hits[0] == GeocodeHit("Springfield, Illinois, United States", 39.8, -89.6)


def test_geocode_city_parses() -> None:
    sample = {
        "results": [
            {"latitude": 47.6, "longitude": -122.3, "name": "Seattle"},
        ]
    }
    with patch("plasmacolorizer.conky.fetch._http_get_json", return_value=sample):
        coords = fetch._geocode_city("Seattle")
    assert coords == (47.6, -122.3)


def test_main_esv_cli(capsys) -> None:
    with patch("plasmacolorizer.conky.fetch.load_conky_settings", return_value=ConkySettings()):
        code = fetch.main(["esv"])
    assert code == 0
    out = capsys.readouterr().out
    assert len(out) > 0
