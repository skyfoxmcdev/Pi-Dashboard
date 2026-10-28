"""Shared helpers for the Pi Dashboard test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.config import validate_config

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """Build a valid configuration with a Paris location and temp cache."""

    raw = json.loads((ROOT / "config" / "config.example.json").read_text(encoding="utf-8"))
    raw["weather"]["cache_file"] = str(tmp_path / "weather-cache.json")
    raw["location"].update(
        {
            "name": "Paris",
            "latitude": 48.8566,
            "longitude": 2.3522,
        }
    )
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(raw.get(key), dict):
            raw[key].update(value)
        else:
            raw[key] = value
    config, warnings = validate_config(raw, ROOT)
    config["_meta"] = {"source": "tests", "warnings": warnings}
    return config
