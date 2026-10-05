from __future__ import annotations

from datetime import date
from typing import Protocol
from zoneinfo import ZoneInfo

from ..config import ScheduleCfg
from ..models import Lesson


class ScheduleFetchError(Exception):
    """Источник недоступен (сеть, HTTP-ошибка, нет файла)."""


class ScheduleFormatError(Exception):
    """Источник ответил, но формат не совпал с ожидаемым (сайт изменился)."""


class ScheduleProvider(Protocol):
    async def fetch(self, date_from: date, date_to: date) -> list[Lesson]:
        """Пары за период (включительно), все подгруппы, время в локальной зоне."""


def build_provider(cfg: ScheduleCfg, tz: ZoneInfo) -> ScheduleProvider:
    if cfg.source == "ics":
        from .ics import IcsProvider

        return IcsProvider(cfg.ics_source, tz)
    from .intime_api import InTimeApiProvider

    return InTimeApiProvider(cfg, tz)
