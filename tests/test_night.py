from __future__ import annotations

import unittest
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.night import is_night, is_night_now, local_now, parse_clock


class NightWindowTests(unittest.TestCase):
    def test_typical_window_inside_and_outside(self) -> None:
        start = parse_clock("22:00")
        end = parse_clock("07:00")
        self.assertFalse(is_night(time(21, 59), start, end))
        self.assertTrue(is_night(time(22, 0), start, end))
        self.assertTrue(is_night(time(23, 59), start, end))

    def test_window_crossing_midnight(self) -> None:
        start = parse_clock("22:00")
        end = parse_clock("07:00")
        self.assertTrue(is_night(time(0, 0), start, end))
        self.assertTrue(is_night(time(6, 59), start, end))
        self.assertFalse(is_night(time(7, 0), start, end))
        self.assertFalse(is_night(time(12, 0), start, end))

    def test_window_within_same_day(self) -> None:
        start = parse_clock("09:00")
        end = parse_clock("17:00")
        self.assertFalse(is_night(time(8, 59), start, end))
        self.assertTrue(is_night(time(12, 0), start, end))
        self.assertFalse(is_night(time(17, 0), start, end))

    def test_equal_bounds_mean_disabled_window(self) -> None:
        moment = parse_clock("23:00")
        self.assertFalse(is_night(moment, moment, moment))

    def test_is_night_now_uses_provided_datetime(self) -> None:
        self.assertTrue(
            is_night_now(
                "22:00",
                "07:00",
                datetime(2026, 10, 28, 23, 30, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(
            is_night_now(
                "22:00",
                "07:00",
                datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc),
            )
        )

    def test_local_now_with_explicit_timezone(self) -> None:
        try:
            ZoneInfo("Europe/Paris")
        except ZoneInfoNotFoundError:
            self.skipTest("base tzdata absente sur cette machine de développement")
        config = {"location": {"timezone": "Europe/Paris"}}
        current = local_now(config)
        self.assertIsNotNone(current.tzinfo)

    def test_parse_clock(self) -> None:
        self.assertEqual(parse_clock("07:05"), time(7, 5))


if __name__ == "__main__":
    unittest.main()
