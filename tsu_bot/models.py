from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Lesson:
    start: datetime  # aware, в локальной зоне
    end: datetime
    title: str
    teacher: str = ""
    room: str = ""  # "302", "Спортивный зал 93"
    building: int | None = None
    room_kind: str = ""  # "Учебная аудитория", "Компьютерный класс"
    lesson_type: str | None = None  # "лекция"/"практика", если источник отдаёт
    online: bool = False
    subgroup: str | None = None  # "а" | "б" | None (общая пара)

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "title": self.title,
            "teacher": self.teacher,
            "room": self.room,
            "building": self.building,
            "room_kind": self.room_kind,
            "lesson_type": self.lesson_type,
            "online": self.online,
            "subgroup": self.subgroup,
        }

    @classmethod
    def from_dict(cls, d: dict, tz: ZoneInfo) -> "Lesson":
        return cls(
            start=datetime.fromisoformat(d["start"]).astimezone(tz),
            end=datetime.fromisoformat(d["end"]).astimezone(tz),
            title=d["title"],
            teacher=d.get("teacher", ""),
            room=d.get("room", ""),
            building=d.get("building"),
            room_kind=d.get("room_kind", ""),
            lesson_type=d.get("lesson_type"),
            online=d.get("online", False),
            subgroup=d.get("subgroup"),
        )
