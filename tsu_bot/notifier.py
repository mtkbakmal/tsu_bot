"""Сборка сообщений из расписания, маршрута и погоды и отправка владельцу."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from .clothing import recommend
from .commute import DayPlan, build_plan
from .config import Settings
from .formatting import change_summary, day_overview, hhmm, weather_block
from .models import Lesson
from .schedule import ScheduleService
from .weather import WeatherClient, WeatherError

log = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        schedule: ScheduleService,
        weather: WeatherClient,
        tz: ZoneInfo,
    ) -> None:
        self.bot = bot
        self.s = settings
        self.schedule = schedule
        self.weather = weather
        self.tz = tz

    async def send(self, text: str) -> None:
        await self.bot.send_message(self.s.env.telegram_owner_id, text)

    def plan(self, lessons: list[Lesson]) -> DayPlan | None:
        return build_plan(lessons, self.s.commute)

    async def _weather(self, plan: DayPlan | None) -> str | None:
        """Погода на время выхода и на конец пар. Нет очных пар: погода не нужна."""
        if plan is None:
            return None
        try:
            leave, end = await self.weather.at([plan.leave_at, plan.last.end])
        except WeatherError as e:
            log.warning("Погода недоступна: %s", e)
            return "Погода: данные сейчас недоступны."
        advice = recommend([leave, end], self.s.weather)
        return weather_block(
            [(f"Выход {hhmm(plan.leave_at)}", leave), (f"Конец пар {hhmm(plan.last.end)}", end)],
            advice,
        )

    async def _day_text(self, day, word: str, *, with_wake: bool, with_weather: bool) -> str:
        lessons = await self.schedule.lessons_for(day)
        plan = self.plan(lessons)
        text = day_overview(word, lessons, plan, with_wake=with_wake)
        if with_weather:
            block = await self._weather(plan)
            if block:
                text += "\n\n" + block
        return text

    async def tomorrow_text(self) -> str:
        """Вечернее сообщение и ответ на кнопку «Что завтра?»."""
        day = self.schedule.today() + timedelta(days=1)
        return await self._day_text(day, "Завтра", with_wake=True, with_weather=True)

    async def morning_text(self) -> str:
        return await self._day_text(
            self.schedule.today(), "Сегодня", with_wake=False, with_weather=True
        )

    async def today_changed_text(self, old: list[Lesson], new: list[Lesson]) -> str:
        head = change_summary(old, new)
        lessons = new
        plan = self.plan(lessons)
        body = day_overview("Сегодня", lessons, plan, with_wake=False)
        now = datetime.now(self.tz)
        if plan is not None and plan.leave_at <= now:
            body = body.replace(f"Выход в {hhmm(plan.leave_at)}. ", "")
        return f"{head}\n\n{body}"

    def reminder_text(self, plan: DayPlan, minutes: int) -> str:
        return (
            f"Выходить через {minutes} мин, в {hhmm(plan.leave_at)}. "
            f"Первая пара в {hhmm(plan.first.start)}."
        )

    def leave_now_text(self, plan: DayPlan) -> str:
        where = f"корпуса {plan.building}" if plan.building is not None else "корпуса"
        return (
            f"Пора выходить. Автобус до главных ворот, затем пешком до {escape(where)}. "
            f"На месте будете к {hhmm(plan.arrive_at)}, первая пара в {hhmm(plan.first.start)}."
        )
