"""Weekly screen-off schedule.

Periods are attached to their *start* day.  An interval such as
``sun 21:40 -> 06:40`` therefore covers Sunday evening and Monday morning.
The dashboard deliberately keeps running while the HDMI output is powered
off; only the video output is disabled.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

DAY_NAMES = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
DAY_SHORT = ("lun", "mar", "mer", "jeu", "ven", "sam", "dim")
MAX_LOOKAHEAD_MINUTES = 8 * 24 * 60


def parse_clock(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def _period_contains(period: dict[str, Any], now: datetime) -> bool:
    start = parse_clock(str(period["start"]))
    end = parse_clock(str(period["end"]))
    days = set(period["days"])
    current = now.time().replace(second=0, microsecond=0)
    weekday = now.weekday()

    if start < end:
        return weekday in days and start <= current < end

    # Overnight period: the start day owns the evening part, the following
    # morning belongs to the same period.
    if weekday in days and current >= start:
        return True
    previous_day = (weekday - 1) % 7
    return previous_day in days and current < end


def is_display_off(now: datetime, schedule: dict[str, Any]) -> bool:
    """Return whether the screen must be off at ``now``."""

    if not schedule.get("enabled", True):
        return False
    return any(_period_contains(period, now) for period in schedule.get("off_periods", []))


def next_change(now: datetime, schedule: dict[str, Any]) -> tuple[datetime, bool] | None:
    """Return the next state transition and its new off/on state.

    The search is bounded to eight days, which is more than enough for a
    weekly schedule.  Minutes are the installation granularity.
    """

    if not schedule.get("enabled", True):
        return None
    current_off = is_display_off(now, schedule)
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(MAX_LOOKAHEAD_MINUTES):
        state = is_display_off(candidate, schedule)
        if state != current_off:
            return candidate, state
        candidate += timedelta(minutes=1)
    return None


def describe_period(period: dict[str, Any]) -> str:
    days = ", ".join(DAY_SHORT[day] for day in period["days"])
    return f"{days} {period['start']}–{period['end']}"


def describe_schedule(schedule: dict[str, Any]) -> str:
    if not schedule.get("enabled", True):
        return "désactivée"
    periods = schedule.get("off_periods", [])
    if not periods:
        return "aucune plage"
    return " ; ".join(describe_period(period) for period in periods)
