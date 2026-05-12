"""Conky fetch helpers (no live network)."""

from __future__ import annotations

from unittest.mock import patch

from plasmacolorizer.conky import fetch
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
    assert "Overcast" in line or "°C" in line


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
