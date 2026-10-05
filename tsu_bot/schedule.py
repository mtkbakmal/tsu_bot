"""Получение расписания, фильтр по подгруппе, кэш в БД и поиск изменений."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from .config import ScheduleCfg
from .models import Lesson
from .parsing import for_subgroup
from .providers import ScheduleProvider

log = logging.getLogger(__name__)


class ScheduleCache(Protocol):
    async def get_days(self, days: list[date]) -> dict[date, list[dict] | None]: ...
    async def save_day(self, day: date, payload: list[dict]) -> None: ...
    async def delete_days_before(self, day: date) -> None: ...


@dataclass
class RefreshResult:
    # день -> (было, стало); только для дней, которые уже были в кэше
    changed: dict[date, tuple[list[Lesson], list[Lesson]]] = field(default_factory=dict)
    total_lessons: int = 0
    had_lessons_before: bool = False


class ScheduleService:
    def __init__(
        self,
        provider: ScheduleProvider,
        cache: ScheduleCache,
        cfg: ScheduleCfg,
        tz: ZoneInfo,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.cfg = cfg
        self.tz = tz

    def today(self) -> date:
        return datetime.now(self.tz).date()

    async def refresh(self, today: date | None = None) -> RefreshResult:
        today = today or self.today()
        days = [today + timedelta(days=i) for i in range(self.cfg.days_ahead)]
        raw = await self.provider.fetch(days[0], days[-1])
        lessons = for_subgroup(raw, self.cfg.subgroup)

        by_day: dict[date, list[Lesson]] = defaultdict(list)
        for l in lessons:
            by_day[l.start.date()].append(l)

        cached = await self.cache.get_days(days)
        result = RefreshResult(total_lessons=len(lessons))
        for d in days:
            new = sorted(by_day.get(d, []), key=lambda l: l.start)
            prev_raw = cached.get(d)
            if prev_raw is not None:
                prev = [Lesson.from_dict(x, self.tz) for x in prev_raw]
                if prev:
                    result.had_lessons_before = True
                if prev == new:
                    continue
                result.changed[d] = (prev, new)
            await self.cache.save_day(d, [l.to_dict() for l in new])
        await self.cache.delete_days_before(today - timedelta(days=1))
        log.info(
            "Расписание обновлено: %d пар, изменённых дней: %d",
            result.total_lessons,
            len(result.changed),
        )
        return result

    async def lessons_for(self, day: date) -> list[Lesson]:
        """Пары дня из кэша; если дня в кэше нет, один раз пробует обновить."""
        cached = (await self.cache.get_days([day])).get(day)
        if cached is None:
            await self.refresh()
            cached = (await self.cache.get_days([day])).get(day)
        return [Lesson.from_dict(x, self.tz) for x in (cached or [])]
