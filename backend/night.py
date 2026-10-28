"""Night-mode time handling, including schedules that cross midnight."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


def parse_clock(value: str) -> time:
    """Parse a validated ``HH:MM`` string into a :class:`datetime.time`."""

    hours, minutes = value.split(":", 1)
    return time(hour=int(hours), minute=int(minutes))


def is_night(at: time, start: time, end: time) -> bool:
    """Return whether ``at`` belongs to the night window.

    A window whose start and end are identical is considered empty, which lets
    an operator disable the effect by setting both values to the same time.
    Night windows that cross midnight (for example 22:00 -> 07:00) are handled.
    """

    if start == end:
        return False
    if start < end:
        return start <= at < end
    return at >= start or at < end


def is_night_now(start: str, end: str, now: datetime | None = None) -> bool:
    """Evaluate the night window for an aware or naive local datetime."""

    current = now or datetime.now().astimezone()
    return is_night(current.time(), parse_clock(start), parse_clock(end))


def local_now(config: dict, now: datetime | None = None) -> datetime:
    """Current time in the configured display timezone.

    ``auto`` means the system timezone, which is what Raspberry Pi OS exposes
    to the kiosk session. An explicit IANA name is used when configured.
    """

    if now is not None:
        return now
    name = config.get("location", {}).get("timezone", "auto")
    if name and name != "auto":
        try:
            return datetime.now(ZoneInfo(name))
        except Exception:
            # Validation happens at startup; this keeps the function total.
            return datetime.now().astimezone()
    return datetime.now().astimezone()
