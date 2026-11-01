"""PRONOTE timetable provider.

The network client is created lazily so that the dashboard still starts when
the optional :mod:`pronotepy` dependency is missing.  Credentials never leave
the backend: the HTTP API only exposes lessons, state and error messages.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from typing import Any, Callable

from .night import local_now

LOGGER = logging.getLogger(__name__)

# Friendly academy names mapped to pronotepy ENT functions.  The complete
# list of functions is documented at https://pronotepy.readthedocs.io.
ACADEMY_ENTS: dict[str, str] = {
    "aix-marseille": "atrium_sud",
    "amiens": "",
    "besancon": "eclat_bfc",
    "bordeaux": "bordeaux",
    "clermont-ferrand": "ent_auvergnerhonealpe",
    "corse": "atrium_sud",
    "creteil": "ile_de_france",
    "dijon": "eclat_bfc",
    "grenoble": "ent_auvergnerhonealpe",
    "guadeloupe": "neoconnect_guadeloupe",
    "guyane": "neoconnect_guadeloupe",
    "lille": "ent_hdf",
    "limoges": "",
    "lyon": "ent_auvergnerhonealpe",
    "martinique": "neoconnect_guadeloupe",
    "mayotte": "ent_mayotte",
    "montpellier": "occitanie_montpellier_educonnect",
    "nancy-metz": "monbureaunumerique",
    "nantes": "",
    "nice": "atrium_sud",
    "normandie": "l_normandie",
    "orleans-tours": "ac_orleans_tours",
    "paris": "paris_classe_numerique",
    "poitiers": "ac_poitiers",
    "reims": "ac_reims",
    "rennes": "ac_rennes",
    "reunion": "ac_reunion",
    "la-reunion": "ac_reunion",
    "auvergne-rhone-alpes": "ent_auvergnerhonealpe",
    "strasbourg": "monbureaunumerique",
    "toulouse": "occitanie_toulouse_edu",
    "versailles": "ile_de_france",
}

DAY_NAMES = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
_ENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,60}$")


class TimetableError(RuntimeError):
    """A user-actionable PRONOTE error."""


@dataclass(frozen=True)
class LessonRecord:
    start: datetime
    end: datetime
    subject: str
    teacher: str | None
    room: str | None
    group: str | None
    canceled: bool
    status: str | None
    test: bool
    outing: bool
    detention: bool


def _safe_error(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:300]


def normalize_academy(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    text = re.sub(r"^academie\s+(de\s+|d')?", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def resolve_ent(academy: str, ent_name: str = "") -> Any | None:
    """Resolve an ENT login function from an academy name or explicit name."""

    try:
        import pronotepy.ent as ent_module
    except ImportError as exc:  # pragma: no cover - exercised on the Pi
        raise TimetableError(
            "pronotepy n'est pas installé. Lancez install.sh ou "
            "pip install -r requirements.txt."
        ) from exc

    if ent_name:
        if not _ENT_NAME_RE.fullmatch(ent_name):
            raise TimetableError("pronote.ent contient un nom invalide.")
        function = getattr(ent_module, ent_name, None)
        if not callable(function) or ent_name.startswith("_"):
            raise TimetableError(f"fonction ENT inconnue dans pronotepy : {ent_name}")
        return function

    key = normalize_academy(academy)
    if not key:
        raise TimetableError(
            "pronote.login vaut ent mais aucune académie n'est configurée."
        )
    function_name = ACADEMY_ENTS.get(key)
    if function_name is None:
        raise TimetableError(
            f"académie non prise en charge : {academy!r}. "
            "Renseignez pronote.academy ou pronote.ent "
            "(par exemple ent_auvergnerhonealpe)."
        )
    if not function_name:
        raise TimetableError(
            f"aucune connexion ENT automatique n'est disponible pour "
            f"l'académie {academy!r}. Utilisez pronote.login=direct ou "
            "renseignez pronote.ent."
        )
    function = getattr(ent_module, function_name, None)
    if not callable(function):
        raise TimetableError(f"fonction ENT absente de pronotepy : {function_name}")
    return function


def _string_attr(value: Any, name: str) -> str | None:
    candidate = getattr(value, name, None)
    if isinstance(candidate, str):
        text = candidate.strip()
        return text or None
    return None


def _lesson_subject(lesson: Any) -> str:
    subject = getattr(lesson, "subject", None)
    name = _string_attr(subject, "name")
    return name or "Cours"


def _lesson_teacher(lesson: Any) -> str | None:
    teacher = _string_attr(lesson, "teacher_name")
    if teacher:
        return teacher
    names = getattr(lesson, "teacher_names", None)
    if isinstance(names, (list, tuple)):
        joined = ", ".join(str(item).strip() for item in names if str(item).strip())
        return joined or None
    return None


def _lesson_room(lesson: Any) -> str | None:
    room = _string_attr(lesson, "classroom")
    if room:
        return room
    rooms = getattr(lesson, "classrooms", None)
    if isinstance(rooms, (list, tuple)):
        joined = ", ".join(str(item).strip() for item in rooms if str(item).strip())
        return joined or None
    return None


def _lesson_group(lesson: Any) -> str | None:
    group = _string_attr(lesson, "group_name")
    if group:
        return group
    groups = getattr(lesson, "group_names", None)
    if isinstance(groups, (list, tuple)):
        joined = ", ".join(str(item).strip() for item in groups if str(item).strip())
        return joined or None
    return None


def lesson_to_record(lesson: Any) -> LessonRecord | None:
    start = getattr(lesson, "start", None)
    end = getattr(lesson, "end", None)
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    if end < start:
        return None
    return LessonRecord(
        start=start,
        end=end,
        subject=_lesson_subject(lesson),
        teacher=_lesson_teacher(lesson),
        room=_lesson_room(lesson),
        group=_lesson_group(lesson),
        canceled=bool(getattr(lesson, "canceled", False)),
        status=_string_attr(lesson, "status"),
        test=bool(getattr(lesson, "test", False)),
        outing=bool(getattr(lesson, "outing", False)),
        detention=bool(getattr(lesson, "detention", False)),
    )


def _serialize_lesson(lesson: LessonRecord) -> dict[str, Any]:
    return {
        "start": lesson.start.strftime("%H:%M"),
        "end": lesson.end.strftime("%H:%M"),
        "subject": lesson.subject,
        "teacher": lesson.teacher,
        "room": lesson.room,
        "group": lesson.group,
        "canceled": lesson.canceled,
        "status": lesson.status,
        "test": lesson.test,
        "outing": lesson.outing,
        "detention": lesson.detention,
    }


def _date_label(day: date) -> str:
    return f"{DAY_NAMES[day.weekday()]} {day.day:02d}/{day.month:02d}"


class TimetableService:
    """Fetch and cache PRONOTE lessons for the current and next school day."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        logger: logging.Logger | None = None,
        now: Callable[[], datetime] | None = None,
        client_factory: Callable[[dict[str, Any]], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.settings = config["pronote"]
        self.logger = logger or LOGGER
        self._now = now or (lambda: local_now(config))
        self._client_factory = client_factory or self._create_client
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: Any | None = None
        self._lessons: dict[date, list[LessonRecord]] = {}
        self._state = "disabled" if not self.settings["enabled"] else "unconfigured"
        self._error: str | None = None
        self._updated_at: datetime | None = None
        self._started = False
        if self.settings["enabled"] and self.configured:
            self._state = "loading"

    @property
    def configured(self) -> bool:
        return bool(
            self.settings["url"]
            and self.settings["username"]
            and self.settings["password"]
        )

    @property
    def enabled(self) -> bool:
        return bool(self.settings["enabled"])

    def start(self) -> None:
        if self._started or not self.enabled or not self.configured:
            return
        self._started = True
        self._thread = threading.Thread(
            target=self._loop,
            name="pronote-timetable",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        self._thread = None
        self._started = False

    def _loop(self) -> None:
        interval = max(300, int(self.settings["refresh_seconds"]))
        while not self._stop.is_set():
            self.refresh_once()
            if self._stop.wait(interval):
                break

    def _create_client(self, settings: dict[str, Any]) -> Any:
        try:
            import pronotepy
        except ImportError as exc:
            raise TimetableError(
                "pronotepy n'est pas installé. Lancez install.sh ou "
                "pip install -r requirements.txt."
            ) from exc

        kwargs: dict[str, Any] = {}
        if settings["login"] == "ent":
            kwargs["ent"] = resolve_ent(settings["academy"], settings["ent"])
        try:
            client = pronotepy.Client(
                settings["url"],
                username=settings["username"],
                password=settings["password"],
                **kwargs,
            )
        except Exception as exc:
            raise TimetableError(f"connexion PRONOTE impossible : {_safe_error(exc)}") from exc
        if not getattr(client, "logged_in", False):
            raise TimetableError("PRONOTE a refusé la connexion.")
        return client

    def _fetch(self, client: Any, start: date, end: date) -> list[Any]:
        session_check = getattr(client, "session_check", None)
        if callable(session_check):
            try:
                session_check()
            except Exception as exc:
                self.logger.debug("PRONOTE session_check : %s", _safe_error(exc))
        return client.lessons(start, end)

    def _record_success(self, lessons: list[Any]) -> None:
        grouped: dict[date, list[LessonRecord]] = {}
        for lesson in lessons:
            record = lesson_to_record(lesson)
            if record is None:
                continue
            grouped.setdefault(record.start.date(), []).append(record)
        for records in grouped.values():
            records.sort(key=lambda item: (item.start, item.end, item.subject))
        self._lessons = grouped
        self._state = "ready"
        self._error = None
        self._updated_at = self._now()

    def refresh_once(self) -> None:
        """Refresh the cache.  Safe to call from tests or the timer thread."""

        with self._lock:
            if not self.enabled:
                self._state = "disabled"
                return
            if not self.configured:
                self._state = "unconfigured"
                return

            today = self._now().date()
            # pronotepy filters on lesson.start; fetching one extra day makes
            # the final day complete even though its date_to becomes midnight.
            end = today + timedelta(days=int(self.settings["days_ahead"]) + 1)
            client = self._client
            try:
                if client is None:
                    client = self._client_factory(self.settings)
                    self._client = client
                lessons = self._fetch(client, today, end)
                self._record_success(lessons)
                self.logger.info(
                    "PRONOTE : %s cours chargés (%s jours)",
                    sum(len(items) for items in self._lessons.values()),
                    len(self._lessons),
                )
            except Exception as exc:
                self._client = None
                message = _safe_error(exc)
                self._error = message
                self._state = "stale" if self._lessons else "error"
                self.logger.warning("PRONOTE indisponible : %s", message)

    def _selected_day(self, now: datetime) -> date:
        today = now.date()
        today_lessons = self._lessons.get(today, [])
        now_naive = now.replace(tzinfo=None)
        if today_lessons:
            last_end = max(lesson.end for lesson in today_lessons)
            if now_naive < last_end:
                return today
        for offset in range(1, int(self.settings["days_ahead"]) + 1):
            candidate = today + timedelta(days=offset)
            if self._lessons.get(candidate):
                return candidate
        return today + timedelta(days=1)

    def snapshot(self) -> dict[str, Any]:
        now = self._now()
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "configured": self.configured,
            "state": self._state,
            "error": self._error,
            "updated_at": self._updated_at.isoformat(timespec="seconds")
            if self._updated_at
            else None,
            "academy": self.settings["academy"] or None,
            "day": None,
            "relative": None,
            "date": None,
            "weekday": None,
            "lessons": [],
        }
        if not self.enabled:
            payload["state"] = "disabled"
            return payload
        if not self.configured:
            payload["state"] = "unconfigured"
            return payload
        if self._state == "loading" and not self._lessons:
            return payload
        if self._state == "error" and not self._lessons:
            return payload

        selected = self._selected_day(now)
        today = now.date()
        relative = (
            "today"
            if selected == today
            else "tomorrow"
            if selected == today + timedelta(days=1)
            else "later"
        )
        records = self._lessons.get(selected, [])
        payload.update(
            {
                "state": "stale" if self._state == "stale" else "ready",
                "day": _date_label(selected),
                "relative": relative,
                "date": selected.isoformat(),
                "weekday": DAY_NAMES[selected.weekday()],
                "lessons": [_serialize_lesson(lesson) for lesson in records],
            }
        )
        return payload
