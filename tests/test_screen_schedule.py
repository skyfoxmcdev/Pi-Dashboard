from __future__ import annotations

import unittest
from datetime import datetime

from backend.screen_schedule import is_display_off, next_change

SCHEDULE = {
    "enabled": True,
    "off_periods": [
        {"days": [0, 1, 2, 3, 4], "start": "21:40", "end": "06:45"},
        {"days": [0, 1, 2, 3, 4], "start": "07:20", "end": "18:00"},
        {"days": [5], "start": "22:00", "end": "11:00"},
        {"days": [6], "start": "21:40", "end": "06:40"},
    ],
}


def at(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute)


class ScreenScheduleTests(unittest.TestCase):
    # 2026-11-02 is a Monday, 2026-11-07 a Saturday, 2026-11-08 a Sunday.
    def test_weekday_evening_and_night(self) -> None:
        self.assertFalse(is_display_off(at(2026, 11, 2, 21, 39), SCHEDULE))
        self.assertTrue(is_display_off(at(2026, 11, 2, 21, 40), SCHEDULE))
        self.assertTrue(is_display_off(at(2026, 11, 3, 6, 44), SCHEDULE))
        self.assertFalse(is_display_off(at(2026, 11, 3, 6, 45), SCHEDULE))

    def test_weekday_daytime_break(self) -> None:
        self.assertFalse(is_display_off(at(2026, 11, 2, 7, 19), SCHEDULE))
        self.assertTrue(is_display_off(at(2026, 11, 2, 7, 20), SCHEDULE))
        self.assertTrue(is_display_off(at(2026, 11, 2, 17, 59), SCHEDULE))
        self.assertFalse(is_display_off(at(2026, 11, 2, 18, 0), SCHEDULE))

    def test_saturday_and_sunday(self) -> None:
        self.assertFalse(is_display_off(at(2026, 11, 7, 10, 59), SCHEDULE))
        self.assertTrue(is_display_off(at(2026, 11, 7, 22, 0), SCHEDULE))
        self.assertTrue(is_display_off(at(2026, 11, 8, 10, 59), SCHEDULE))
        self.assertFalse(is_display_off(at(2026, 11, 8, 11, 0), SCHEDULE))
        self.assertTrue(is_display_off(at(2026, 11, 8, 21, 40), SCHEDULE))
        self.assertTrue(is_display_off(at(2026, 11, 9, 6, 39), SCHEDULE))
        self.assertFalse(is_display_off(at(2026, 11, 9, 6, 40), SCHEDULE))
        self.assertFalse(is_display_off(at(2026, 11, 9, 7, 19), SCHEDULE))

    def test_disabled_schedule_never_turns_off(self) -> None:
        self.assertFalse(
            is_display_off(at(2026, 11, 2, 22, 0), {**SCHEDULE, "enabled": False})
        )

    def test_next_change(self) -> None:
        moment, off = next_change(at(2026, 11, 2, 7, 19), SCHEDULE)
        self.assertEqual(moment, at(2026, 11, 2, 7, 20))
        self.assertTrue(off)

        moment, off = next_change(at(2026, 11, 2, 17, 59), SCHEDULE)
        self.assertEqual(moment, at(2026, 11, 2, 18, 0))
        self.assertFalse(off)

    def test_empty_periods(self) -> None:
        empty = {"enabled": True, "off_periods": []}
        self.assertFalse(is_display_off(at(2026, 11, 2, 22, 0), empty))
        self.assertIsNone(next_change(at(2026, 11, 2, 22, 0), empty))


if __name__ == "__main__":
    unittest.main()
