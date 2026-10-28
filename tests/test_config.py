from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.config import ConfigError, load_config, validate_config
from tests.helpers import ROOT, make_config


class LoadConfigTests(unittest.TestCase):
    def test_example_config_is_valid_and_warns_about_coordinates(self) -> None:
        config = load_config(ROOT / "config" / "config.example.json")
        self.assertEqual(config["server"]["host"], "127.0.0.1")
        self.assertEqual(config["server"]["port"], 8080)
        self.assertIsNone(config["location"]["latitude"])
        warnings = config["_meta"]["warnings"]
        self.assertTrue(any("Coordonnées" in warning for warning in warnings))

    def test_missing_file_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as context:
                load_config(Path(tmp) / "absent.json")
        self.assertIn("introuvable", str(context.exception))

    def test_invalid_json_reports_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{ nope", encoding="utf-8")
            with self.assertRaises(ConfigError) as context:
                load_config(path)
        self.assertIn("JSON invalide", str(context.exception))

    def test_relative_cache_path_is_resolved_against_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw = json.loads((ROOT / "config" / "config.example.json").read_text(encoding="utf-8"))
            raw["weather"]["cache_file"] = "cache.json"
            config, _ = validate_config(raw, tmp_path)
            self.assertEqual(Path(config["weather"]["cache_file"]), (tmp_path / "cache.json").resolve())


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.raw = json.loads((ROOT / "config" / "config.example.json").read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def validate(self):
        return validate_config(self.raw, self.tmp_path)

    def test_rejects_non_loopback_host(self) -> None:
        self.raw["server"]["host"] = "0.0.0.0"
        with self.assertRaises(ConfigError):
            self.validate()

    def test_rejects_privileged_port(self) -> None:
        self.raw["server"]["port"] = 80
        with self.assertRaises(ConfigError):
            self.validate()

    def test_boolean_is_not_a_port(self) -> None:
        self.raw["server"]["port"] = True
        with self.assertRaises(ConfigError):
            self.validate()

    def test_coordinates_must_be_provided_together(self) -> None:
        self.raw["location"]["latitude"] = 48.85
        with self.assertRaises(ConfigError):
            self.validate()

    def test_rejects_out_of_range_latitude(self) -> None:
        self.raw["location"]["latitude"] = 91
        self.raw["location"]["longitude"] = 2.35
        with self.assertRaises(ConfigError):
            self.validate()

    def test_rejects_bad_night_time(self) -> None:
        self.raw["night_mode"]["start"] = "25:00"
        with self.assertRaises(ConfigError):
            self.validate()

    def test_accepts_night_window_across_midnight(self) -> None:
        self.raw["night_mode"]["start"] = "22:30"
        self.raw["night_mode"]["end"] = "06:45"
        config, _warnings = self.validate()
        self.assertEqual(config["night_mode"]["start"], "22:30")
        self.assertEqual(config["night_mode"]["end"], "06:45")

    def test_rejects_unknown_timezone(self) -> None:
        self.raw["location"]["timezone"] = "Mars/Olympus"
        with self.assertRaises(ConfigError):
            self.validate()

    def test_rejects_unsupported_weather_provider(self) -> None:
        self.raw["weather"]["provider"] = "example"
        with self.assertRaises(ConfigError):
            self.validate()

    def test_rejects_invalid_unit(self) -> None:
        self.raw["weather"]["wind_speed_unit"] = "warp"
        with self.assertRaises(ConfigError):
            self.validate()

    def test_rejects_too_frequent_weather_refresh(self) -> None:
        self.raw["weather"]["refresh_seconds"] = 30
        with self.assertRaises(ConfigError):
            self.validate()

    def test_rejects_bad_threshold_order(self) -> None:
        self.raw["system"]["thresholds"]["temperature_warn_c"] = 90
        self.raw["system"]["thresholds"]["temperature_critical_c"] = 80
        with self.assertRaises(ConfigError):
            self.validate()

    def test_unknown_keys_only_warn(self) -> None:
        self.raw["server"]["extra"] = "ignored"
        config, warnings = self.validate()
        self.assertNotIn("extra", config["server"])
        self.assertTrue(any("server.extra" in warning for warning in warnings))

    def test_coordinates_configured_suppresses_coordinate_warning(self) -> None:
        config = make_config(self.tmp_path)
        warnings = config["_meta"]["warnings"]
        self.assertFalse(any("Coordonnées" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
