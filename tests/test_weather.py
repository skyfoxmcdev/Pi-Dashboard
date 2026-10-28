from __future__ import annotations

import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from backend.weather import (
    WeatherError,
    WeatherService,
    build_forecast_url,
    normalize_forecast,
)
from tests.helpers import load_fixture, make_config


def silent_logger() -> logging.Logger:
    logger = logging.getLogger("tests.weather.silent")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


class ForecastUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_url_contains_required_open_meteo_parameters(self) -> None:
        url = build_forecast_url(self.config)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "api.open-meteo.com")
        self.assertEqual(query["latitude"], ["48.856600"])
        self.assertEqual(query["longitude"], ["2.352200"])
        self.assertEqual(query["timezone"], ["auto"])
        self.assertEqual(query["forecast_days"], ["6"])
        self.assertIn("temperature_2m", query["current"][0])
        self.assertIn("precipitation_probability", query["hourly"][0])
        self.assertIn("precipitation_probability_max", query["daily"][0])
        self.assertIn("sunrise", query["daily"][0])
        self.assertNotIn("precipitation", query["daily"][0].split(","))

    def test_url_rejects_unconfigured_coordinates(self) -> None:
        self.config["location"]["latitude"] = None
        self.config["location"]["longitude"] = None
        with self.assertRaises(WeatherError):
            build_forecast_url(self.config)

    def test_url_uses_configured_units_and_timezone(self) -> None:
        self.config["weather"]["temperature_unit"] = "fahrenheit"
        self.config["weather"]["wind_speed_unit"] = "mph"
        self.config["weather"]["precipitation_unit"] = "inch"
        self.config["location"]["timezone"] = "Europe/Paris"
        query = parse_qs(urlsplit(build_forecast_url(self.config)).query)
        self.assertEqual(query["temperature_unit"], ["fahrenheit"])
        self.assertEqual(query["wind_speed_unit"], ["mph"])
        self.assertEqual(query["precipitation_unit"], ["inch"])
        self.assertEqual(query["timezone"], ["Europe/Paris"])


class NormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(Path(self.tmp.name))
        self.payload = load_fixture("open_meteo.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_normalizes_current_hourly_daily_and_sun(self) -> None:
        data = normalize_forecast(self.payload, self.config)
        current = data["current"]
        self.assertEqual(current["temperature"], 12.4)
        self.assertEqual(current["apparent_temperature"], 10.9)
        self.assertEqual(current["humidity_percent"], 68)
        self.assertEqual(current["wind_direction"], "SO")
        self.assertEqual(current["condition"], "Partiellement nuageux")
        self.assertEqual(current["icon"], "partly-day")

        self.assertEqual(len(data["hourly"]), 8)
        self.assertEqual(data["hourly"][0]["time"], "2026-10-28T15:00")
        self.assertEqual(data["hourly"][-1]["time"], "2026-10-28T22:00")
        self.assertEqual(data["hourly"][0]["icon"], "cloudy")
        self.assertEqual(data["hourly"][1]["icon"], "rain")
        self.assertEqual(data["hourly"][5]["icon"], "clear-night")

        self.assertEqual(len(data["daily"]), 5)
        self.assertEqual(data["daily"][0]["date"], "2026-10-28")
        self.assertEqual(data["daily"][3]["condition"], "Ciel dégagé")
        self.assertEqual(data["daily"][3]["icon"], "clear-day")
        self.assertEqual(data["sun"]["sunrise"], "2026-10-28T07:32")
        self.assertEqual(data["sun"]["sunset"], "2026-10-28T18:21")
        self.assertEqual(data["timezone"], "Europe/Paris")
        self.assertEqual(data["units"]["temperature"], "°C")

    def test_rejects_incomplete_current_weather(self) -> None:
        del self.payload["current"]["temperature_2m"]
        with self.assertRaises(WeatherError):
            normalize_forecast(self.payload, self.config)

    def test_rejects_missing_hourly_block(self) -> None:
        del self.payload["hourly"]
        with self.assertRaises(WeatherError):
            normalize_forecast(self.payload, self.config)

    def test_unknown_weather_code_is_handled(self) -> None:
        self.payload["current"]["weather_code"] = 250
        data = normalize_forecast(self.payload, self.config)
        self.assertEqual(data["current"]["condition"], "Conditions inconnues")
        self.assertEqual(data["current"]["icon"], "unknown")

    def test_day_icon_switches_at_night(self) -> None:
        self.payload["current"]["weather_code"] = 0
        self.payload["current"]["is_day"] = 0
        data = normalize_forecast(self.payload, self.config)
        self.assertEqual(data["current"]["icon"], "clear-night")


class WeatherServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.config = make_config(self.tmp_path)
        self.payload = load_fixture("open_meteo.json")
        self.now = 1_800_000_000.0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_service(self, fetcher):
        return WeatherService(
            self.config,
            logger=silent_logger(),
            fetcher=fetcher,
            clock=lambda: self.now,
        )

    def test_successful_refresh_populates_snapshot_and_cache(self) -> None:
        service = self.make_service(lambda url, timeout: self.payload)
        self.assertTrue(service.refresh())
        snapshot = service.snapshot()
        self.assertEqual(snapshot["state"], "ok")
        self.assertEqual(snapshot["current"]["temperature"], 12.4)
        self.assertEqual(snapshot["age_seconds"], 0)
        self.assertEqual(snapshot["online"], True)
        self.assertIsNotNone(snapshot["updated_at"])
        self.assertTrue(Path(self.config["weather"]["cache_file"]).is_file())
        cache = json.loads(Path(self.config["weather"]["cache_file"]).read_text(encoding="utf-8"))
        self.assertEqual(cache["cache_version"], 1)
        self.assertEqual(cache["location"]["latitude"], 48.8566)
        self.assertEqual(cache["data"]["current"]["temperature"], 12.4)

    def test_loaded_cache_is_marked_stale_after_failed_refresh(self) -> None:
        first = self.make_service(lambda url, timeout: self.payload)
        self.assertTrue(first.refresh())
        self.now += 1000
        second = self.make_service(lambda url, timeout: (_ for _ in ()).throw(WeatherError("panne")))
        self.assertEqual(second.snapshot()["state"], "ok")
        self.assertFalse(second.refresh())
        snapshot = second.snapshot()
        self.assertEqual(snapshot["state"], "stale")
        self.assertEqual(snapshot["current"]["temperature"], 12.4)
        self.assertEqual(snapshot["online"], False)
        self.assertIn("panne", snapshot["error"])

    def test_cache_from_different_coordinates_is_ignored(self) -> None:
        first = self.make_service(lambda url, timeout: self.payload)
        self.assertTrue(first.refresh())
        self.config["location"]["longitude"] = 1.0
        second = self.make_service(lambda url, timeout: self.payload)
        snapshot = second.snapshot()
        self.assertIsNone(snapshot["current"])
        self.assertEqual(snapshot["state"], "loading")

    def test_corrupt_cache_is_ignored(self) -> None:
        Path(self.config["weather"]["cache_file"]).write_text("{broken", encoding="utf-8")
        service = self.make_service(lambda url, timeout: self.payload)
        snapshot = service.snapshot()
        self.assertIsNone(snapshot["current"])
        self.assertEqual(snapshot["state"], "loading")

    def test_unconfigured_location_reports_unconfigured(self) -> None:
        self.config["location"]["latitude"] = None
        self.config["location"]["longitude"] = None
        service = self.make_service(lambda url, timeout: self.payload)
        snapshot = service.snapshot()
        self.assertEqual(snapshot["state"], "unconfigured")
        self.assertIn("Coordonnées", snapshot["error"])
        self.assertIsNone(snapshot["online"])

    def test_failure_without_cache_is_unavailable(self) -> None:
        service = self.make_service(lambda url, timeout: (_ for _ in ()).throw(WeatherError("hors ligne")))
        self.assertFalse(service.refresh())
        snapshot = service.snapshot()
        self.assertEqual(snapshot["state"], "unavailable")
        self.assertIn("hors ligne", snapshot["error"])
        self.assertEqual(snapshot["online"], False)

    def test_stale_age_marks_cache_stale_even_without_attempt(self) -> None:
        first = self.make_service(lambda url, timeout: self.payload)
        self.assertTrue(first.refresh())
        self.now += int(self.config["weather"]["refresh_seconds"]) * 3
        second = self.make_service(lambda url, timeout: self.payload)
        self.assertEqual(second.snapshot()["state"], "stale")

    def test_snapshot_does_not_expose_mutable_internal_data(self) -> None:
        service = self.make_service(lambda url, timeout: self.payload)
        self.assertTrue(service.refresh())
        snapshot = service.snapshot()
        snapshot["current"]["temperature"] = -99
        self.assertEqual(service.snapshot()["current"]["temperature"], 12.4)

    def test_background_start_refreshes_even_with_fresh_cache(self) -> None:
        first = self.make_service(lambda url, timeout: self.payload)
        self.assertTrue(first.refresh())

        called = threading.Event()

        def fetcher(url, timeout):
            called.set()
            return self.payload

        second = self.make_service(fetcher)
        try:
            second.start()
            self.assertTrue(called.wait(2.0), "le thread météo n'a pas actualisé au démarrage")
        finally:
            second.stop()


if __name__ == "__main__":
    unittest.main()
