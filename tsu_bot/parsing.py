"""Разбор строк расписания InTime (SUMMARY и LOCATION из ICS)."""
from __future__ import annotations

import re

from .models import Lesson

# "Название, (932603)" / "Название, (932603 (а))"
_SUMMARY_RE = re.compile(
    r"^(?P<title>.*?)[\s,]*\((?P<group>[\w\-]+)(?:\s*\((?P<sub>[^)]*)\))?\)\s*$"
)
# "302 (2) Учебная аудитория" / "Спортивный зал 93 (14)"
_LOCATION_RE = re.compile(r"^(?P<room>.*?)\s*\((?P<building>\d+)\)\s*(?P<kind>.*)$")


def parse_summary(summary: str) -> tuple[str, str | None]:
    """-> (название, подгруппа|None). Подгруппа приводится к нижнему регистру."""
    summary = summary.strip()
    m = _SUMMARY_RE.match(summary)
    if not m:
        return summary, None
    sub = (m.group("sub") or "").strip().lower() or None
    return m.group("title").strip(), sub


def parse_location(location: str) -> tuple[str, int | None, str, bool]:
    """-> (аудитория, корпус|None, тип помещения, онлайн?)."""
    loc = location.strip()
    low = loc.lower()
    if low.startswith(("онлайн", "дистанц", "online")):
        return "", None, "", True
    m = _LOCATION_RE.match(loc)
    if not m:
        return loc, None, "", False
    return (
        m.group("room").strip(),
        int(m.group("building")),
        m.group("kind").strip(),
        False,
    )


def for_subgroup(lessons: list[Lesson], subgroup: str) -> list[Lesson]:
    """Оставляет общие пары и пары указанной подгруппы."""
    sg = subgroup.strip().lower()
    return [l for l in lessons if l.subgroup is None or l.subgroup == sg]
