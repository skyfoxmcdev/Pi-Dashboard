"""Configuration loading and validation for Pi Dashboard.

The configuration is a plain JSON file. Validation is strict on values that
affect security (bind address, port) or the weather request, while unknown keys
only produce warnings so that a configuration remains forward compatible.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8080,
    },
    "location": {
        "name": "Votre ville (à configurer)",
        "latitude": None,
        "longitude": None,
        "timezone": "auto",
    },
    "weather": {
        "provider": "open-meteo",
        "refresh_seconds": 900,
        "request_timeout_seconds": 8,
        "cache_file": "/var/lib/pi-dashboard/weather-cache.json",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    },
    "night_mode": {
        "enabled": True,
        "start": "22:00",
        "end": "07:00",
    },
    "system": {
        "refresh_seconds": 2,
        "thresholds": {
            "cpu_warn_percent": 80,
            "cpu_critical_percent": 95,
            "memory_warn_percent": 80,
            "memory_critical_percent": 95,
            "temperature_warn_c": 70,
            "temperature_critical_c": 80,
        },
    },
    "ui": {
        "poll_seconds": 10,
    },
}

TEMPERATURE_UNITS = {"celsius", "fahrenheit"}
WIND_SPEED_UNITS = {"kmh", "ms", "mph", "kn"}
PRECIPITATION_UNITS = {"mm", "inch"}


class ConfigError(ValueError):
    """Raised when the configuration file is missing or invalid."""


def _warn_unknown_keys(
    raw: dict[str, Any],
    defaults: dict[str, Any],
    prefix: str,
    warnings: list[str],
) -> None:
    for key in raw:
        if key not in defaults:
            warnings.append(f"clé inconnue ignorée : {prefix}{key}")
        elif isinstance(raw[key], dict) and isinstance(defaults[key], dict):
            _warn_unknown_keys(raw[key], defaults[key], f"{prefix}{key}.", warnings)


def _merge(defaults: Any, raw: Any) -> Any:
    if isinstance(defaults, dict) and isinstance(raw, dict):
        merged = copy.deepcopy(defaults)
        for key, value in raw.items():
            if key in defaults:
                merged[key] = _merge(defaults[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
    return copy.deepcopy(raw)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{field} doit être un objet JSON.")
    return value


def _number(
    value: Any,
    field: str,
    minimum: float,
    maximum: float,
    *,
    allow_none: bool = False,
) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} doit être un nombre.")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ConfigError(
            f"{field} doit être compris entre {minimum:g} et {maximum:g}."
        )
    return number


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field} doit être un entier.")
    if not minimum <= value <= maximum:
        raise ConfigError(
            f"{field} doit être compris entre {minimum} et {maximum}."
        )
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field} doit être un booléen.")
    return value


def _string(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{field} doit être une chaîne de caractères.")
    text = value.strip()
    if not text:
        raise ConfigError(f"{field} ne peut pas être vide.")
    if len(text) > maximum:
        raise ConfigError(f"{field} ne peut pas dépasser {maximum} caractères.")
    return text


def _validate_time(value: Any, field: str) -> str:
    if not isinstance(value, str) or not TIME_PATTERN.match(value):
        raise ConfigError(f"{field} doit être au format HH:MM (24 heures).")
    return value


def _validate_thresholds(raw: dict[str, Any]) -> dict[str, Any]:
    thresholds = _mapping(raw, "system.thresholds")
    result = {
        "cpu_warn_percent": _number(
            thresholds.get("cpu_warn_percent", 80),
            "system.thresholds.cpu_warn_percent",
            1,
            100,
        ),
        "cpu_critical_percent": _number(
            thresholds.get("cpu_critical_percent", 95),
            "system.thresholds.cpu_critical_percent",
            1,
            100,
        ),
        "memory_warn_percent": _number(
            thresholds.get("memory_warn_percent", 80),
            "system.thresholds.memory_warn_percent",
            1,
            100,
        ),
        "memory_critical_percent": _number(
            thresholds.get("memory_critical_percent", 95),
            "system.thresholds.memory_critical_percent",
            1,
            100,
        ),
        "temperature_warn_c": _number(
            thresholds.get("temperature_warn_c", 70),
            "system.thresholds.temperature_warn_c",
            0,
            120,
        ),
        "temperature_critical_c": _number(
            thresholds.get("temperature_critical_c", 80),
            "system.thresholds.temperature_critical_c",
            0,
            120,
        ),
    }
    for name in ("cpu", "memory"):
        if result[f"{name}_warn_percent"] >= result[f"{name}_critical_percent"]:
            raise ConfigError(
                f"system.thresholds.{name}_warn_percent doit être inférieur "
                f"à {name}_critical_percent."
            )
    if result["temperature_warn_c"] >= result["temperature_critical_c"]:
        raise ConfigError(
            "system.thresholds.temperature_warn_c doit être inférieur à "
            "temperature_critical_c."
        )
    return result


def validate_config(raw: dict[str, Any], base_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Return a normalized configuration and a list of warnings."""

    if not isinstance(raw, dict):
        raise ConfigError("La racine du fichier de configuration doit être un objet JSON.")

    warnings: list[str] = []
    _warn_unknown_keys(raw, DEFAULT_CONFIG, "", warnings)
    config = _merge(DEFAULT_CONFIG, raw)

    server = _mapping(config["server"], "server")
    host = _string(server.get("host"), "server.host", 64)
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(
            "server.host doit être 127.0.0.1 (ou localhost). "
            "Pi Dashboard est volontairement limité à l'interface locale."
        )
    port = _integer(server.get("port"), "server.port", 1024, 65535)

    location = _mapping(config["location"], "location")
    name = _string(location.get("name"), "location.name", 80)
    latitude = _number(
        location.get("latitude"),
        "location.latitude",
        -90,
        90,
        allow_none=True,
    )
    longitude = _number(
        location.get("longitude"),
        "location.longitude",
        -180,
        180,
        allow_none=True,
    )
    if (latitude is None) != (longitude is None):
        raise ConfigError(
            "location.latitude et location.longitude doivent être renseignés ensemble."
        )
    if latitude is None:
        warnings.append(
            "Coordonnées météo non renseignées : la météo sera indisponible "
            "jusqu'à la configuration de location.latitude et location.longitude."
        )

    timezone = _string(location.get("timezone"), "location.timezone", 64)
    if timezone != "auto":
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(
                f"location.timezone inconnu : {timezone!r}. "
                "Utilisez « auto » ou un nom IANA comme Europe/Paris."
            ) from exc

    weather = _mapping(config["weather"], "weather")
    provider = _string(weather.get("provider"), "weather.provider", 32)
    if provider != "open-meteo":
        raise ConfigError("weather.provider doit valoir open-meteo.")
    refresh_seconds = _integer(
        weather.get("refresh_seconds"), "weather.refresh_seconds", 300, 86400
    )
    timeout_seconds = _integer(
        weather.get("request_timeout_seconds"),
        "weather.request_timeout_seconds",
        3,
        30,
    )
    cache_file = _string(weather.get("cache_file"), "weather.cache_file", 4096)
    cache_path = Path(cache_file).expanduser()
    if not cache_path.is_absolute():
        cache_path = base_dir / cache_path
    cache_path = cache_path.resolve(strict=False)
    if cache_path.exists() and cache_path.is_dir():
        raise ConfigError("weather.cache_file ne doit pas être un répertoire.")
    temperature_unit = _string(
        weather.get("temperature_unit"), "weather.temperature_unit", 16
    )
    wind_speed_unit = _string(
        weather.get("wind_speed_unit"), "weather.wind_speed_unit", 16
    )
    precipitation_unit = _string(
        weather.get("precipitation_unit"), "weather.precipitation_unit", 16
    )
    if temperature_unit not in TEMPERATURE_UNITS:
        raise ConfigError(
            "weather.temperature_unit doit être celsius ou fahrenheit."
        )
    if wind_speed_unit not in WIND_SPEED_UNITS:
        raise ConfigError(
            "weather.wind_speed_unit doit être kmh, ms, mph ou kn."
        )
    if precipitation_unit not in PRECIPITATION_UNITS:
        raise ConfigError("weather.precipitation_unit doit être mm ou inch.")

    night_mode = _mapping(config["night_mode"], "night_mode")
    night_enabled = _boolean(night_mode.get("enabled"), "night_mode.enabled")
    night_start = _validate_time(night_mode.get("start"), "night_mode.start")
    night_end = _validate_time(night_mode.get("end"), "night_mode.end")

    system = _mapping(config["system"], "system")
    system_refresh = _integer(
        system.get("refresh_seconds"), "system.refresh_seconds", 1, 60
    )
    thresholds = _validate_thresholds(system.get("thresholds"))

    ui = _mapping(config["ui"], "ui")
    poll_seconds = _integer(ui.get("poll_seconds"), "ui.poll_seconds", 5, 120)

    normalized: dict[str, Any] = {
        "server": {"host": host, "port": port},
        "location": {
            "name": name,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": timezone,
        },
        "weather": {
            "provider": provider,
            "refresh_seconds": refresh_seconds,
            "request_timeout_seconds": timeout_seconds,
            "cache_file": str(cache_path),
            "temperature_unit": temperature_unit,
            "wind_speed_unit": wind_speed_unit,
            "precipitation_unit": precipitation_unit,
        },
        "night_mode": {
            "enabled": night_enabled,
            "start": night_start,
            "end": night_end,
        },
        "system": {
            "refresh_seconds": system_refresh,
            "thresholds": {k: float(v) for k, v in thresholds.items()},
        },
        "ui": {"poll_seconds": poll_seconds},
    }
    return normalized, warnings


def load_config(path: str | Path) -> dict[str, Any]:
    """Load, validate and normalize a JSON configuration file."""

    config_path = Path(path).expanduser()
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Fichier de configuration introuvable : {config_path}\n"
            "Copiez config/config.example.json vers "
            "/etc/pi-dashboard/config.json puis adaptez-le."
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Impossible de lire la configuration {config_path} : {exc}"
        ) from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"JSON invalide dans {config_path} (ligne {exc.lineno}, "
            f"colonne {exc.colno}) : {exc.msg}"
        ) from exc

    normalized, warnings = validate_config(raw, config_path.parent.resolve())
    normalized["_meta"] = {
        "source": str(config_path.resolve()),
        "warnings": warnings,
    }
    return normalized


def system_timezone_name() -> str | None:
    """Best-effort IANA timezone name of the running system."""

    # Debian/Raspberry Pi OS keeps the name in /etc/timezone.
    try:
        name = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if name:
            ZoneInfo(name)
            return name
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass

    # /etc/localtime is usually a symlink into /usr/share/zoneinfo.
    try:
        target = Path("/etc/localtime").resolve()
        marker = "/zoneinfo/"
        text = str(target)
        if marker in text:
            name = text.split(marker, 1)[1]
            ZoneInfo(name)
            return name
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass

    return None


def display_timezone(config: dict[str, Any]) -> str | None:
    """Timezone used by the UI: explicit IANA name, or system timezone."""

    configured = config["location"]["timezone"]
    if configured != "auto":
        return configured
    return system_timezone_name()
