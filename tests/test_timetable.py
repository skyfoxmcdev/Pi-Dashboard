from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.timetable import TimetableService
from tests.helpers import make_config


class Subject:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeLesson:
    def __init__(
        self,
        start: datetime,
        end: datetime,
        subject: str,
        *,
        canceled: bool = False,
        room: str = "A12",
        teacher: str = "Mme Martin",
        test: bool = False,
    ) -> None:
        self.start = start
        self.end = end
        self.subject = Subject(subject)
        self.canceled = canceled
        self.classroom = room
        self.teacher_name = teacher
        self.group_name = None
        self.test = test
        self.outing = False
        self.detention = False
        self.status = None


class FakeClient:
    logged_in = True

    def __init__(self, lessons: list[FakeLesson]) -> None:
        self._lessons = lessons
        self.calls = 0

    def lessons(self, _start, _end):
        self.calls += 1
        return list(self._lessons)


class FailingClient:
    logged_in = True

    def lessons(self, _start, _end):
        raise RuntimeError("PRONOTE ne répond pas")


class TimetableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def config(self, **pronote):
        values = {
            "enabled": True,
            "url": "https://lycee.index-education.net/pronote/eleve.html",
            "username": "eleve",
            "password": "secret",
            "login": "direct",
            "academy": "Grenoble",
        }
        values.update(pronote)
        return make_config(self.tmp_path, pronote=values)

    def service(self, config, lessons, now):
        client = FakeClient(lessons)
        service = TimetableService(
            config,
            now=lambda: now,
            client_factory=lambda _settings: client,
        )
        return service, client

    def test_current_day_timetable_is_serialized(self) -> None:
        now = datetime(2026, 11, 2, 10, 0)
        lessons = [
            FakeLesson(datetime(2026, 11, 2, 8, 0), datetime(2026, 11, 2, 9, 0), "Maths"),
            FakeLesson(
                datetime(2026, 11, 2, 10, 0),
                datetime(2026, 11, 2, 11, 0),
                "Français",
                room="B03",
                test=True,
            ),
        ]
        config = self.config()
        service, client = self.service(config, lessons, now)
        service.refresh_once()
        payload = service.snapshot()
        self.assertEqual(client.calls, 1)
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(payload["relative"], "today")
        self.assertEqual(payload["date"], "2026-11-02")
        self.assertEqual(len(payload["lessons"]), 2)
        self.assertEqual(payload["lessons"][1]["start"], "10:00")
        self.assertEqual(payload["lessons"][1]["subject"], "Français")
        self.assertEqual(payload["lessons"][1]["room"], "B03")
        self.assertTrue(payload["lessons"][1]["test"])
        self.assertNotIn("password", payload)
        self.assertNotIn("username", payload)

    def test_next_school_day_after_last_lesson(self) -> None:
        now = datetime(2026, 11, 2, 19, 0)
        lessons = [
            FakeLesson(datetime(2026, 11, 2, 8, 0), datetime(2026, 11, 2, 17, 0), "Histoire"),
            FakeLesson(datetime(2026, 11, 3, 9, 0), datetime(2026, 11, 3, 10, 0), "SVT"),
        ]
        config = self.config()
        service, _client = self.service(config, lessons, now)
        service.refresh_once()
        payload = service.snapshot()
        self.assertEqual(payload["relative"], "tomorrow")
        self.assertEqual(payload["date"], "2026-11-03")
        self.assertEqual(payload["lessons"][0]["subject"], "SVT")

    def test_next_day_with_lessons_skips_empty_days(self) -> None:
        # Friday evening: Saturday and Sunday are empty, Monday has lessons.
        now = datetime(2026, 11, 6, 20, 0)
        lessons = [
            FakeLesson(datetime(2026, 11, 6, 8, 0), datetime(2026, 11, 6, 17, 0), "Anglais"),
            FakeLesson(datetime(2026, 11, 9, 8, 0), datetime(2026, 11, 9, 9, 0), "Maths"),
        ]
        config = self.config()
        service, _client = self.service(config, lessons, now)
        service.refresh_once()
        payload = service.snapshot()
        self.assertEqual(payload["relative"], "later")
        self.assertEqual(payload["date"], "2026-11-09")
        self.assertEqual(payload["lessons"][0]["subject"], "Maths")

    def test_unconfigured_and_disabled_states(self) -> None:
        config = self.config(url="", username="", password="")
        service = TimetableService(config, now=lambda: datetime(2026, 11, 2, 10, 0))
        self.assertEqual(service.snapshot()["state"], "unconfigured")
        self.assertIn("configured", service.snapshot())

        disabled_config = self.config(enabled=False)
        disabled = TimetableService(disabled_config, now=lambda: datetime(2026, 11, 2, 10, 0))
        self.assertEqual(disabled.snapshot()["state"], "disabled")

    def test_error_without_cache_is_reported(self) -> None:
        config = self.config()
        service = TimetableService(
            config,
            now=lambda: datetime(2026, 11, 2, 10, 0),
            client_factory=lambda _settings: FailingClient(),
        )
        service.refresh_once()
        payload = service.snapshot()
        self.assertEqual(payload["state"], "error")
        self.assertIn("PRONOTE", payload["error"])
        self.assertEqual(payload["lessons"], [])

    def test_stale_cache_keeps_last_timetable(self) -> None:
        now = datetime(2026, 11, 2, 9, 30)
        lessons = [
            FakeLesson(datetime(2026, 11, 2, 9, 0), datetime(2026, 11, 2, 11, 0), "Maths")
        ]
        config = self.config()
        success, _client = self.service(config, lessons, now)
        success.refresh_once()
        success._client_factory = lambda _settings: FailingClient()
        success._client = None
        success.refresh_once()
        payload = success.snapshot()
        self.assertEqual(payload["state"], "stale")
        self.assertEqual(len(payload["lessons"]), 1)
        self.assertIn("PRONOTE", payload["error"])

    def test_canceled_lesson_is_kept_with_flag(self) -> None:
        now = datetime(2026, 11, 2, 8, 30)
        lessons = [
            FakeLesson(
                datetime(2026, 11, 2, 8, 0),
                datetime(2026, 11, 2, 9, 0),
                "EPS",
                canceled=True,
            )
        ]
        config = self.config()
        service, _client = self.service(config, lessons, now)
        service.refresh_once()
        payload = service.snapshot()
        self.assertTrue(payload["lessons"][0]["canceled"])


if __name__ == "__main__":
    unittest.main()
