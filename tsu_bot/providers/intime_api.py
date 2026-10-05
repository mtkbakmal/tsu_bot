"""Источник: JSON API InTime (intime.tsu.ru/api/web/v1).

Формат ответа (проверен на реальном ответе):

    {"grid": [{"date": "2026-09-30", "lessons": [
        {"type": "EMPTY", "starts": 6300, "ends": 12000, "lessonNumber": 1},
        {"type": "LESSON", "title": "...", "lessonType": "LECTURE",
         "groups": [{"id": "...", "name": "932603 (б)", "isSubgroup": true}],
         "professor": {"fullName": "..."},
         "audience": {"name": "302 (2) Учебная аудитория", "building": {"name": "2 корпус"}},
         "starts": 12900, "ends": 18600}, ...]}]}

`starts`/`ends` - секунды от полуночи UTC указанной даты. Если сайт снова
изменится, будет ScheduleFormatError и уведомление в Telegram, а не тихий мусор.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..config import ScheduleCfg
from ..models import Lesson
from ..parsing import parse_location
from . import ScheduleFetchError, ScheduleFormatError

log = logging.getLogger(__name__)

LESSON_TYPES = {
    "LECTURE": "лекция",
    "SEMINAR": "семинар",
    "PRACTICE": "практика",
    "PRACTICAL": "практика",
    "LABORATORY": "лабораторная",
    "LAB": "лабораторная",
    "CONSULTATION": "консультация",
    "EXAM": "экзамен",
    "CREDIT": "зачёт",
    "TEST": "зачёт",
}

_SUB_RE = re.compile(r"\(\s*([а-яa-z])\s*\)\s*$", re.IGNORECASE)
_BUILDING_RE = re.compile(r"^\s*(\d+)")


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ScheduleFormatError(msg)


def _subgroup(groups: Any, group_id: str) -> str | None:
    """Подгруппа нашей группы в этой паре: 'а' | 'б' | None (общая пара).

    Если в паре несколько подгрупп сразу (или есть запись «вся группа»),
    пара общая и подгруппой не помечается.
    """
    if not isinstance(groups, list):
        return None
    mine = [g for g in groups if isinstance(g, dict) and g.get("id") == group_id]
    entries = mine or [g for g in groups if isinstance(g, dict)]
    if not entries or any(not g.get("isSubgroup") for g in entries):
        return None
    subs = set()
    for g in entries:
        m = _SUB_RE.search(str(g.get("name", "")))
        if m:
            subs.add(m.group(1).lower())
    return subs.pop() if len(subs) == 1 else None


def _location(audience: Any) -> tuple[str, int | None, str, bool]:
    if not isinstance(audience, dict):
        return "", None, "", False  # аудитория не назначена
    name = str(audience.get("name") or audience.get("shortName") or "")
    room, building, kind, online = parse_location(name)
    if building is None and not online:
        b = audience.get("building")
        m = _BUILDING_RE.match(str(b.get("name", ""))) if isinstance(b, dict) else None
        if m:
            building = int(m.group(1))
    return room, building, kind, online


def _dt(day: date, seconds: Any, tz: ZoneInfo) -> datetime:
    _require(isinstance(seconds, (int, float)), f"starts/ends не число: {seconds!r}")
    midnight_utc = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return (midnight_utc + timedelta(seconds=seconds)).astimezone(tz)


def payload_to_lessons(payload: Any, tz: ZoneInfo, group_id: str = "") -> list[Lesson]:
    _require(isinstance(payload, dict) and isinstance(payload.get("grid"), list),
             "В ответе нет списка grid")
    lessons: list[Lesson] = []
    for day_obj in payload["grid"]:
        _require(isinstance(day_obj, dict) and isinstance(day_obj.get("lessons"), list),
                 "В дне сетки нет списка lessons")
        try:
            day = date.fromisoformat(str(day_obj["date"])[:10])
        except (KeyError, ValueError) as e:
            raise ScheduleFormatError(f"Некорректная дата дня: {day_obj.get('date')!r}") from e

        for raw in day_obj["lessons"]:
            if not isinstance(raw, dict) or raw.get("type") == "EMPTY":
                continue  # пустой слот сетки
            title = str(raw.get("title") or "").strip()
            _require(bool(title), f"У пары нет названия (type={raw.get('type')!r})")
            if raw.get("type") != "LESSON":
                log.warning("Неизвестный тип элемента сетки: %r (%s)", raw.get("type"), title)

            room, building, kind, online = _location(raw.get("audience"))
            lt = raw.get("lessonType")
            prof = raw.get("professor")
            lessons.append(
                Lesson(
                    start=_dt(day, raw.get("starts"), tz),
                    end=_dt(day, raw.get("ends"), tz),
                    title=title,
                    teacher=str(prof.get("fullName", "")).strip() if isinstance(prof, dict) else "",
                    room=room,
                    building=building,
                    room_kind=kind,
                    lesson_type=LESSON_TYPES.get(str(lt).upper(), str(lt).lower()) if lt else None,
                    online=online,
                    subgroup=_subgroup(raw.get("groups"), group_id),
                )
            )
    lessons.sort(key=lambda l: l.start)
    return lessons


class InTimeApiProvider:
    def __init__(self, cfg: ScheduleCfg, tz: ZoneInfo) -> None:
        self.cfg = cfg
        self.tz = tz

    def url(self, date_from: date, date_to: date) -> str:
        return self.cfg.api_url_template.format(
            base=self.cfg.api_base_url.rstrip("/"),
            faculty_id=self.cfg.faculty_id,
            group_id=self.cfg.group_id,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
        )

    async def fetch_raw(self, date_from: date, date_to: date) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=20, follow_redirects=True, headers={"Accept": "application/json"}
            ) as c:
                r = await c.get(self.url(date_from, date_to))
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise ScheduleFetchError(f"InTime недоступен: {e}") from e
        try:
            return r.json()
        except ValueError as e:
            raise ScheduleFormatError("InTime вернул не JSON") from e

    async def fetch(self, date_from: date, date_to: date) -> list[Lesson]:
        payload = await self.fetch_raw(date_from, date_to)
        lessons = payload_to_lessons(payload, self.tz, self.cfg.group_id)
        return [l for l in lessons if date_from <= l.start.date() <= date_to]
