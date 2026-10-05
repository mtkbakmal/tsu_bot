"""Источник: ICS-экспорт расписания InTime (файл или ссылка)."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from ..models import Lesson
from ..parsing import parse_location, parse_summary
from . import ScheduleFetchError, ScheduleFormatError


def parse_ics(data: bytes, tz: ZoneInfo) -> list[Lesson]:
    try:
        cal = Calendar.from_ical(data)
    except Exception as e:  # icalendar бросает ValueError и др.
        raise ScheduleFormatError(f"Не удалось разобрать ICS: {e}") from e

    lessons: list[Lesson] = []
    for ev in cal.walk("VEVENT"):
        try:
            start = ev.decoded("DTSTART")
            end = ev.decoded("DTEND")
        except Exception as e:
            raise ScheduleFormatError(f"Событие без DTSTART/DTEND: {e}") from e
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            continue  # событие на весь день, не пара
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=tz)

        title, subgroup = parse_summary(str(ev.get("SUMMARY", "")))
        room, building, kind, online = parse_location(str(ev.get("LOCATION", "")))
        lessons.append(
            Lesson(
                start=start.astimezone(tz),
                end=end.astimezone(tz),
                title=title,
                teacher=str(ev.get("DESCRIPTION", "")).strip(),
                room=room,
                building=building,
                room_kind=kind,
                lesson_type=None,  # в ICS-экспорте InTime типа занятия нет
                online=online,
                subgroup=subgroup,
            )
        )
    lessons.sort(key=lambda l: l.start)
    return lessons


class IcsProvider:
    def __init__(self, source: str, tz: ZoneInfo) -> None:
        self.source = source
        self.tz = tz

    async def _read(self) -> bytes:
        if self.source.startswith(("http://", "https://")):
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                    r = await c.get(self.source)
                    r.raise_for_status()
                    return r.content
            except httpx.HTTPError as e:
                raise ScheduleFetchError(f"ICS недоступен: {e}") from e
        try:
            return await asyncio.to_thread(Path(self.source).read_bytes)
        except OSError as e:
            raise ScheduleFetchError(f"Не удалось прочитать {self.source}: {e}") from e

    async def fetch(self, date_from: date, date_to: date) -> list[Lesson]:
        lessons = parse_ics(await self._read(), self.tz)
        return [l for l in lessons if date_from <= l.start.date() <= date_to]
