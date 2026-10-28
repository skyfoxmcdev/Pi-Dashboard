"""Application service assembling the JSON contract consumed by the UI."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import APP_NAME, __version__
from .config import display_timezone
from .night import is_night_now, local_now
from .network import NetworkInfo
from .system_metrics import SystemMetrics
from .weather import WeatherService


class DashboardApp:
    """Own the data services and expose ``status``/``health`` payloads."""

    def __init__(
        self,
        config: dict[str, Any],
        frontend_dir: Path | str,
        *,
        logger: logging.Logger | None = None,
        weather: WeatherService | None = None,
        metrics: SystemMetrics | None = None,
        network: NetworkInfo | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.frontend_dir = Path(frontend_dir)
        self.logger = logger or logging.getLogger(__name__)
        self.weather = weather or WeatherService(config, logger=self.logger)
        self.metrics = metrics or SystemMetrics(config["system"])
        self.network = network or NetworkInfo()
        self._clock = clock
        self._now = now or (lambda: local_now(config))
        self._started_monotonic = clock()
        self._started_at = self._now().isoformat(timespec="seconds")
        self._started = False

    def start_background(self) -> None:
        if self._started:
            return
        self.metrics.prime()
        self.weather.start()
        self._started = True

    def stop_background(self) -> None:
        self.weather.stop()
        self._started = False

    def _uptime(self) -> int:
        return max(0, int(self._clock() - self._started_monotonic))

    def status(self) -> dict[str, Any]:
        now = self._now()
        weather = self.weather.snapshot()
        network = self.network.collect()
        system = self.metrics.collect()
        network["online"] = weather.get("online")

        night_config = self.config["night_mode"]
        night_active = (
            is_night_now(night_config["start"], night_config["end"], now)
            if night_config["enabled"]
            else False
        )
        location = self.config["location"]

        return {
            "app": {
                "name": APP_NAME,
                "version": __version__,
                "started_at": self._started_at,
                "uptime_seconds": self._uptime(),
            },
            "generated_at": now.isoformat(timespec="seconds"),
            "timezone": display_timezone(self.config),
            "location": {
                "name": location["name"],
                "configured": location["latitude"] is not None,
            },
            "night": {
                "enabled": night_config["enabled"],
                "active": night_active,
                "start": night_config["start"],
                "end": night_config["end"],
            },
            "weather": weather,
            "system": system,
            "network": network,
            "ui": {
                "poll_seconds": self.config["ui"]["poll_seconds"],
            },
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": APP_NAME,
            "version": __version__,
            "uptime_seconds": self._uptime(),
            "weather_state": self.weather.snapshot().get("state"),
            "time": self._now().isoformat(timespec="seconds"),
        }
