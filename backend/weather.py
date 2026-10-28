"""Open-Meteo integration with caching and a background refresh loop.

The frontend never calls a weather provider directly. This service owns the
only outbound HTTP request, keeps a normalized snapshot, and falls back to the
last successful disk cache when the network is unavailable.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .weather_codes import describe_weather, wind_direction_label

API_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_VERSION = 1
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_HOURLY_ITEMS = 8
MAX_DAILY_ITEMS = 5

CURRENT_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "is_day",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
    "wind_direction_10m",
)
HOURLY_FIELDS = (
    "temperature_2m",
    "weather_code",
    "precipitation_probability",
    "is_day",
)
DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "sunrise",
    "sunset",
    "precipitation_probability_max",
)

UNIT_SYMBOLS = {
    "celsius": "°C",
    "fahrenheit": "°F",
    "kmh": "km/h",
    "ms": "m/s",
    "mph": "mph",
    "kn": "nœuds",
    "mm": "mm",
    "inch": "in",
}


class WeatherError(Exception):
    """An expected weather data/transport error with a user-safe message."""


def unit_symbols(config: dict[str, Any]) -> dict[str, str]:
    weather = config["weather"]
    return {
        "temperature": UNIT_SYMBOLS[weather["temperature_unit"]],
        "wind_speed": UNIT_SYMBOLS[weather["wind_speed_unit"]],
        "precipitation": UNIT_SYMBOLS[weather["precipitation_unit"]],
    }


def build_forecast_url(config: dict[str, Any]) -> str:
    """Build the Open-Meteo request for the configured location and units."""

    location = config["location"]
    latitude = location["latitude"]
    longitude = location["longitude"]
    if latitude is None or longitude is None:
        raise WeatherError("Coordonnées météo non configurées.")

    weather = config["weather"]
    timezone = location["timezone"]
    params = {
        "latitude": f"{float(latitude):.6f}",
        "longitude": f"{float(longitude):.6f}",
        "current": ",".join(CURRENT_FIELDS),
        "hourly": ",".join(HOURLY_FIELDS),
        "daily": ",".join(DAILY_FIELDS),
        "timezone": "auto" if timezone == "auto" else timezone,
        "timeformat": "iso8601",
        "forecast_days": "6",
        "temperature_unit": weather["temperature_unit"],
        "wind_speed_unit": weather["wind_speed_unit"],
        "precipitation_unit": weather["precipitation_unit"],
    }
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    """Fetch and decode a bounded JSON document from Open-Meteo."""

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"PiDashboard/{__version__} (Raspberry Pi kiosk)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        raise WeatherError(
            f"Le service météo a répondu avec une erreur HTTP {exc.code}."
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise WeatherError(
                "Le service météo n'a pas répondu dans le délai imparti."
            ) from exc
        raise WeatherError(
            "Impossible de joindre le service météo. Vérifiez la connexion Internet."
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise WeatherError(
            "Le service météo n'a pas répondu dans le délai imparti."
        ) from exc
    except OSError as exc:
        raise WeatherError(
            "Impossible de joindre le service météo. Vérifiez la connexion Internet."
        ) from exc

    if len(payload) > MAX_RESPONSE_BYTES:
        raise WeatherError("La réponse météo est trop volumineuse.")
    try:
        decoded = payload.decode(charset)
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, LookupError) as exc:
        raise WeatherError("La réponse du service météo est illisible.") from exc
    if not isinstance(data, dict):
        raise WeatherError("La réponse du service météo est invalide.")
    return data


def _round(value: Any, digits: int = 1) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _weather_code(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_day(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return default


def _require_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise WeatherError(f"Champ météo manquant ou invalide : {key}.")
    return value


def _require_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise WeatherError(f"Champ météo manquant ou invalide : {key}.")
    return value


def normalize_forecast(
    payload: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """Turn an Open-Meteo response into the stable dashboard schema."""

    current_raw = _require_mapping(payload, "current")
    hourly_raw = _require_mapping(payload, "hourly")
    daily_raw = _require_mapping(payload, "daily")

    current_temperature = _round(current_raw.get("temperature_2m"))
    current_code = _weather_code(current_raw.get("weather_code"))
    if current_temperature is None or current_code is None:
        raise WeatherError("La météo actuelle est incomplète dans la réponse.")

    current_day = _is_day(current_raw.get("is_day"), True)
    current_label, current_icon = describe_weather(current_code, current_day)
    current_wind_direction = _integer(current_raw.get("wind_direction_10m"))
    current = {
        "temperature": current_temperature,
        "apparent_temperature": _round(current_raw.get("apparent_temperature")),
        "humidity_percent": _integer(current_raw.get("relative_humidity_2m")),
        "precipitation": _round(current_raw.get("precipitation")),
        "weather_code": current_code,
        "condition": current_label,
        "icon": current_icon,
        "is_day": current_day,
        "wind_speed": _round(current_raw.get("wind_speed_10m")),
        "wind_direction_degrees": current_wind_direction,
        "wind_direction": wind_direction_label(current_wind_direction),
    }

    hourly_times = hourly_raw.get("time")
    hourly_times = hourly_times if isinstance(hourly_times, list) else []
    current_time = current_raw.get("time")
    current_time = current_time if isinstance(current_time, str) else ""
    hourly: list[dict[str, Any]] = []
    for index, timestamp in enumerate(hourly_times):
        if not isinstance(timestamp, str):
            continue
        if current_time and timestamp < current_time:
            continue
        code = _weather_code(_at(hourly_raw.get("weather_code"), index))
        day = _is_day(_at(hourly_raw.get("is_day"), index), True)
        label, icon = describe_weather(code, day)
        hourly.append(
            {
                "time": timestamp,
                "temperature": _round(_at(hourly_raw.get("temperature_2m"), index)),
                "weather_code": code,
                "condition": label,
                "icon": icon,
                "precipitation_probability": _integer(
                    _at(hourly_raw.get("precipitation_probability"), index)
                ),
                "is_day": day,
            }
        )
        if len(hourly) >= MAX_HOURLY_ITEMS:
            break

    daily_dates = daily_raw.get("time")
    daily_dates = daily_dates if isinstance(daily_dates, list) else []
    daily: list[dict[str, Any]] = []
    for index, date in enumerate(daily_dates):
        if not isinstance(date, str):
            continue
        code = _weather_code(_at(daily_raw.get("weather_code"), index))
        label, icon = describe_weather(code, True)
        daily.append(
            {
                "date": date,
                "weather_code": code,
                "condition": label,
                "icon": icon,
                "temperature_max": _round(
                    _at(daily_raw.get("temperature_2m_max"), index)
                ),
                "temperature_min": _round(
                    _at(daily_raw.get("temperature_2m_min"), index)
                ),
                "precipitation_probability": _integer(
                    _at(daily_raw.get("precipitation_probability_max"), index)
                ),
            }
        )
        if len(daily) >= MAX_DAILY_ITEMS:
            break

    sunrise = _at(daily_raw.get("sunrise"), 0)
    sunset = _at(daily_raw.get("sunset"), 0)
    sun = {
        "sunrise": sunrise if isinstance(sunrise, str) else None,
        "sunset": sunset if isinstance(sunset, str) else None,
    }

    timezone_name = payload.get("timezone")
    if not isinstance(timezone_name, str) or not timezone_name:
        configured = config["location"]["timezone"]
        timezone_name = None if configured == "auto" else configured

    return {
        "timezone": timezone_name,
        "units": unit_symbols(config),
        "current": current,
        "hourly": hourly,
        "daily": daily,
        "sun": sun,
    }


def _at(values: Any, index: int) -> Any:
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return None


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, WeatherError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        return f"Le service météo a répondu avec une erreur HTTP {exc.code}."
    if isinstance(exc, urllib.error.URLError):
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return "Le service météo n'a pas répondu dans le délai imparti."
        return "Impossible de joindre le service météo. Vérifiez la connexion Internet."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Le service météo n'a pas répondu dans le délai imparti."
    return "Erreur inattendue lors de la mise à jour météo."


class WeatherService:
    """Own the weather snapshot, cache, and refresh thread."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        logger: logging.Logger | None = None,
        fetcher: Callable[[str, float], dict[str, Any]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._location = config["location"]
        self._weather = config["weather"]
        self._configured = (
            self._location.get("latitude") is not None
            and self._location.get("longitude") is not None
        )
        self._logger = logger or logging.getLogger(__name__)
        self._fetcher = fetcher or fetch_json
        self._clock = clock
        self._cache_path = Path(self._weather["cache_file"])
        self._lock = threading.RLock()
        self._data: dict[str, Any] | None = None
        self._fetched_epoch: float | None = None
        self._last_error: str | None = None
        self._last_attempt_ok: bool | None = None
        self._failures = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        if self._configured:
            self.load_cache()

    @property
    def configured(self) -> bool:
        return self._configured

    def load_cache(self) -> bool:
        """Load the last successful snapshot if it matches the configuration."""

        if not self._configured:
            return False
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except (OSError, json.JSONDecodeError) as exc:
            self._logger.warning("Cache météo illisible (%s).", exc.__class__.__name__)
            return False

        try:
            if raw.get("cache_version") != CACHE_VERSION:
                return False
            cached_location = raw.get("location", {})
            if not self._same_location(cached_location):
                self._logger.info("Cache météo ignoré : coordonnées différentes.")
                return False
            fetched_epoch = float(raw["fetched_epoch"])
            data = raw["data"]
            if not isinstance(data, dict):
                return False
            if data.get("units") != unit_symbols(self._config):
                self._logger.info("Cache météo ignoré : unités différentes.")
                return False
            if not isinstance(data.get("current"), dict):
                return False
            if not isinstance(data.get("hourly"), list):
                return False
            if not isinstance(data.get("daily"), list):
                return False
        except (KeyError, TypeError, ValueError):
            self._logger.warning("Cache météo invalide, ignoré.")
            return False

        with self._lock:
            self._data = data
            self._fetched_epoch = fetched_epoch
            self._last_attempt_ok = None
            self._last_error = None
        self._logger.info("Cache météo chargé (âge %.0f s).", max(0, self._clock() - fetched_epoch))
        return True

    def _same_location(self, cached: Any) -> bool:
        if not isinstance(cached, dict):
            return False
        try:
            return (
                abs(float(cached["latitude"]) - float(self._location["latitude"])) < 1e-6
                and abs(float(cached["longitude"]) - float(self._location["longitude"])) < 1e-6
            )
        except (KeyError, TypeError, ValueError):
            return False

    def start(self) -> None:
        if not self._configured or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="weather-refresh",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def refresh(self) -> bool:
        """Perform one weather request and update the snapshot."""

        if not self._configured:
            return False
        try:
            url = build_forecast_url(self._config)
            payload = self._fetcher(url, float(self._weather["request_timeout_seconds"]))
            if not isinstance(payload, dict):
                raise WeatherError("La réponse du service météo est invalide.")
            normalized = normalize_forecast(payload, self._config)
            fetched_epoch = self._clock()
            normalized["updated_at"] = datetime.fromtimestamp(fetched_epoch).astimezone().isoformat(
                timespec="seconds"
            )
            with self._lock:
                self._data = normalized
                self._fetched_epoch = fetched_epoch
                self._last_error = None
                self._last_attempt_ok = True
                self._failures = 0
            self._write_cache(normalized, fetched_epoch)
            self._logger.info(
                "Météo actualisée : %.1f %s, %s.",
                normalized["current"]["temperature"],
                normalized["units"]["temperature"],
                normalized["current"]["condition"],
            )
            return True
        except Exception as exc:  # noqa: BLE001 - errors must never kill the kiosk
            message = _safe_error(exc)
            with self._lock:
                self._last_error = message
                self._last_attempt_ok = False
                self._failures += 1
            self._logger.warning("Échec de mise à jour météo : %s", message)
            self._logger.debug("Détail météo", exc_info=True)
            return False

    def _write_cache(self, data: dict[str, Any], fetched_epoch: float) -> None:
        cache_payload = {
            "cache_version": CACHE_VERSION,
            "fetched_epoch": fetched_epoch,
            "location": {
                "latitude": self._location["latitude"],
                "longitude": self._location["longitude"],
            },
            "data": data,
        }
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self._cache_path.parent),
                prefix=".weather-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(cache_payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
            os.replace(str(temporary), str(self._cache_path))
            try:
                os.chmod(self._cache_path, 0o640)
            except OSError:
                pass
        except OSError as exc:
            self._logger.warning("Impossible d'écrire le cache météo : %s", exc)
            try:
                if "temporary" in locals():
                    temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def snapshot(self) -> dict[str, Any]:
        """Return the JSON-ready weather block for /api/status."""

        units = unit_symbols(self._config)
        base: dict[str, Any] = {
            "configured": self._configured,
            "provider": "open-meteo",
            "units": units,
            "updated_at": None,
            "age_seconds": None,
            "timezone": None,
            "current": None,
            "hourly": [],
            "daily": [],
            "sun": None,
            "error": None,
            "online": None,
        }

        if not self._configured:
            base["state"] = "unconfigured"
            base["error"] = (
                "Coordonnées météo non configurées. Renseignez location.latitude "
                "et location.longitude dans /etc/pi-dashboard/config.json."
            )
            return base

        with self._lock:
            data = copy.deepcopy(self._data)
            fetched_epoch = self._fetched_epoch
            last_error = self._last_error
            last_attempt_ok = self._last_attempt_ok

        if data is None:
            base["state"] = "loading" if last_error is None else "unavailable"
            base["error"] = last_error
            base["online"] = last_attempt_ok
            return base

        now = self._clock()
        age = max(0, int(now - (fetched_epoch or now)))
        refresh_seconds = int(self._weather["refresh_seconds"])
        if last_attempt_ok is False:
            state = "stale"
        elif age > refresh_seconds * 2:
            state = "stale"
        else:
            state = "ok"

        base.update(
            {
                "state": state,
                "updated_at": data.get("updated_at"),
                "age_seconds": age,
                "timezone": data.get("timezone"),
                "current": data.get("current"),
                "hourly": data.get("hourly", []),
                "daily": data.get("daily", []),
                "sun": data.get("sun"),
                "error": last_error,
                "online": last_attempt_ok,
            }
        )
        return base

    def _age_seconds(self) -> int | None:
        with self._lock:
            if self._fetched_epoch is None:
                return None
            return max(0, int(self._clock() - self._fetched_epoch))

    def _next_delay(self) -> float:
        with self._lock:
            has_data = self._data is not None
            attempt_ok = self._last_attempt_ok
            failures = self._failures
        if not has_data or attempt_ok is False:
            exponent = min(max(failures - 1, 0), 4)
            return float(min(600, 60 * (2**exponent)))
        age = self._age_seconds() or 0
        return float(max(30, int(self._weather["refresh_seconds"]) - age))

    def _run(self) -> None:
        # Always validate connectivity once at startup, even when a fresh cache
        # was loaded: this determines the Internet indicator promptly and makes
        # sure a reboot does not hide a long network outage behind a stale file.
        first_run = True
        while not self._stop.is_set():
            age = self._age_seconds()
            refresh_seconds = int(self._weather["refresh_seconds"])
            needs_refresh = first_run or age is None or age >= refresh_seconds
            with self._lock:
                if self._last_attempt_ok is False:
                    needs_refresh = True
            if needs_refresh:
                self.refresh()
            first_run = False
            if self._stop.wait(self._next_delay()):
                break
