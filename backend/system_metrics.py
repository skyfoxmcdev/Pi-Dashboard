"""Lightweight Linux system metrics for the dashboard.

All readings come from procfs/sysfs; no external process is spawned. A ``root``
path can be injected so the parsers and collectors are testable off-device.
"""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, Callable


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_proc_stat(text: str) -> dict[str, int] | None:
    """Parse the aggregate ``cpu`` line of /proc/stat."""

    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()
        if len(parts) < 5:
            return None
        try:
            values = [int(part) for part in parts[1:]]
        except ValueError:
            return None
        # user nice system idle iowait irq softirq steal [...]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return {"total": sum(values), "idle": idle}
    return None


def cpu_percent_from_samples(
    previous: dict[str, int] | None, current: dict[str, int] | None
) -> float | None:
    """CPU utilisation between two /proc/stat samples."""

    if not previous or not current:
        return None
    total_delta = current["total"] - previous["total"]
    idle_delta = current["idle"] - previous["idle"]
    if total_delta <= 0:
        return None
    percent = 100.0 * (1.0 - (idle_delta / total_delta))
    return round(min(100.0, max(0.0, percent)), 1)


def parse_meminfo(text: str) -> dict[str, int] | None:
    """Parse the fields needed for RAM usage, in bytes."""

    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        parts = raw.strip().split()
        if not parts:
            continue
        try:
            values[key] = int(parts[0]) * 1024
        except ValueError:
            continue

    total = values.get("MemTotal")
    if not total or total <= 0:
        return None
    available = values.get("MemAvailable")
    if available is None:
        available = (
            values.get("MemFree", 0)
            + values.get("Buffers", 0)
            + values.get("Cached", 0)
        )
    available = min(total, max(0, available))
    used = total - available
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "percent": round(100.0 * used / total, 1),
    }


def parse_uptime(text: str) -> float | None:
    parts = text.split()
    if not parts:
        return None
    try:
        return max(0.0, float(parts[0]))
    except ValueError:
        return None


def parse_loadavg(text: str) -> list[float] | None:
    parts = text.split()
    if len(parts) < 3:
        return None
    try:
        return [round(float(part), 2) for part in parts[:3]]
    except ValueError:
        return None


def parse_cpu_temperature(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    if abs(value) > 1000:
        value /= 1000.0
    if not -40.0 <= value <= 150.0:
        return None
    return round(value, 1)


def evaluate_health(
    cpu_percent: float | None,
    memory_percent: float | None,
    temperature_c: float | None,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    """Classify overall system health against configured thresholds."""

    warnings: list[str] = []
    critical: list[str] = []

    if cpu_percent is not None:
        if cpu_percent >= thresholds["cpu_critical_percent"]:
            critical.append(f"Processeur saturé ({cpu_percent:.0f} %)")
        elif cpu_percent >= thresholds["cpu_warn_percent"]:
            warnings.append(f"Processeur chargé ({cpu_percent:.0f} %)")

    if memory_percent is not None:
        if memory_percent >= thresholds["memory_critical_percent"]:
            critical.append(f"Mémoire saturée ({memory_percent:.0f} %)")
        elif memory_percent >= thresholds["memory_warn_percent"]:
            warnings.append(f"Mémoire chargée ({memory_percent:.0f} %)")

    if temperature_c is not None:
        if temperature_c >= thresholds["temperature_critical_c"]:
            critical.append(f"Température CPU élevée ({temperature_c:.0f} °C)")
        elif temperature_c >= thresholds["temperature_warn_c"]:
            warnings.append(f"Température CPU tiède ({temperature_c:.0f} °C)")

    if critical:
        return {
            "level": "critical",
            "label": "Critique",
            "reasons": critical + warnings,
        }
    if warnings:
        return {
            "level": "warn",
            "label": "À surveiller",
            "reasons": warnings,
        }
    if (
        cpu_percent is None
        and memory_percent is None
        and temperature_c is None
    ):
        return {
            "level": "unknown",
            "label": "Indisponible",
            "reasons": ["Métriques système indisponibles sur cette plateforme."],
        }
    return {
        "level": "ok",
        "label": "Système sain",
        "reasons": [],
    }


class SystemMetrics:
    """Read, cache and summarize the Raspberry Pi system state."""

    def __init__(
        self,
        system_config: dict[str, Any],
        *,
        root: Path | str = Path("/"),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._root = Path(root)
        self._refresh_seconds = float(system_config["refresh_seconds"])
        self._thresholds = dict(system_config["thresholds"])
        self._clock = clock
        self._lock = threading.RLock()
        self._last_cpu: dict[str, int] | None = None
        self._cache: dict[str, Any] | None = None
        self._cache_time = 0.0

    def prime(self) -> None:
        """Take an initial CPU sample so the first status has a delta."""

        with self._lock:
            self._last_cpu = self._read_cpu_times()

    def _read_cpu_times(self) -> dict[str, int] | None:
        text = _read_text(self._root / "proc" / "stat")
        return parse_proc_stat(text) if text else None

    def collect(self) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            if self._cache is not None and (now - self._cache_time) < self._refresh_seconds:
                return copy.deepcopy(self._cache)

            current_cpu = self._read_cpu_times()
            cpu_percent = cpu_percent_from_samples(self._last_cpu, current_cpu)
            if current_cpu is not None:
                self._last_cpu = current_cpu

            mem_text = _read_text(self._root / "proc" / "meminfo")
            memory = parse_meminfo(mem_text) if mem_text else None

            uptime_text = _read_text(self._root / "proc" / "uptime")
            uptime_seconds = parse_uptime(uptime_text) if uptime_text else None

            load_text = _read_text(self._root / "proc" / "loadavg")
            load_average = parse_loadavg(load_text) if load_text else None

            temp_raw = _read_text(
                self._root / "sys" / "class" / "thermal" / "thermal_zone0" / "temp"
            )
            temperature_c = parse_cpu_temperature(temp_raw)

            memory_percent = memory["percent"] if memory else None
            result: dict[str, Any] = {
                "available": any(
                    value is not None
                    for value in (cpu_percent, memory, temperature_c, uptime_seconds)
                ),
                "cpu_percent": cpu_percent,
                "memory": memory,
                "cpu_temperature_c": temperature_c,
                "uptime_seconds": (
                    int(uptime_seconds) if uptime_seconds is not None else None
                ),
                "load_average": load_average,
                "health": evaluate_health(
                    cpu_percent, memory_percent, temperature_c, self._thresholds
                ),
            }
            self._cache = result
            self._cache_time = now
            return copy.deepcopy(result)
