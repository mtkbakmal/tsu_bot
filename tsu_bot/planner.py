"""Планировщик: обновление расписания, утренняя сводка, напоминания, вечернее сообщение."""
from __future__ import annotations

import functools
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .alerts import Alerter
from .config import Settings
from .db import Database
from .notifier import Notifier
from .providers import ScheduleFetchError, ScheduleFormatError
from .schedule import ScheduleService

log = logging.getLogger(__name__)

FETCH_FAILS_BEFORE_ALERT = 3


def guarded(name: str):
    """Ошибка в задаче не роняет сервис: пишется в лог и приходит владельцу (с паузой между повторами)."""

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self: "Planner", *args, **kwargs):
            try:
                return await fn(self, *args, **kwargs)
            except Exception as e:
                log.exception("Ошибка в задаче %s", name)
                await self.alerter.alert(f"job:{name}", f"Ошибка в задаче «{name}»: {type(e).__name__}: {e}")

        return wrapper

    return deco


class Planner:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        schedule: ScheduleService,
        notifier: Notifier,
        alerter: Alerter,
        tz: ZoneInfo,
    ) -> None:
        self.s = settings
        self.db = db
        self.schedule = schedule
        self.notifier = notifier
        self.alerter = alerter
        self.tz = tz
        self.scheduler = AsyncIOScheduler(timezone=tz)
        self._fetch_failures = 0
        self._today_job_ids: list[str] = []

    # --- жизненный цикл ----------------------------------------------------

    def start(self) -> None:
        sch = self.s.schedule
        n = self.s.notify
        self.scheduler.add_job(
            self.refresh_job, IntervalTrigger(minutes=sch.refresh_minutes), id="refresh",
            coalesce=True, max_instances=1,
        )
        self.scheduler.add_job(
            self.plan_today, CronTrigger(hour=0, minute=5), id="plan-today", coalesce=True,
        )
        self.scheduler.add_job(
            self.evening_job,
            CronTrigger(hour=n.evening_clock.hour, minute=n.evening_clock.minute),
            id="evening", coalesce=True, misfire_grace_time=600,
        )
        self.scheduler.add_job(
            self.purge_job, CronTrigger(hour=3, minute=0), id="purge", coalesce=True,
        )
        self.scheduler.start()

    async def startup(self) -> None:
        """Первичное обновление и планирование (запускается фоном, не блокируя бота)."""
        await self.refresh_job()
        await self.plan_today()
        now = datetime.now(self.tz)
        if now.time() >= self.s.notify.evening_clock:
            await self.evening_job()  # догоняем, если перезапуск случился после вечернего времени

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    # --- задачи ------------------------------------------------------------

    @guarded("обновление расписания")
    async def refresh_job(self) -> None:
        try:
            result = await self.schedule.refresh()
        except ScheduleFormatError as e:
            await self.alerter.alert(
                "schedule-format",
                f"Формат расписания изменился, парсер нужно поправить: {e}",
            )
            return
        except ScheduleFetchError as e:
            self._fetch_failures += 1
            log.warning("Ошибка получения расписания (%d подряд): %s", self._fetch_failures, e)
            if self._fetch_failures >= FETCH_FAILS_BEFORE_ALERT:
                await self.alerter.alert(
                    "schedule-fetch",
                    f"Не удаётся получить расписание уже {self._fetch_failures} раз подряд: {e}",
                )
            return

        self._fetch_failures = 0
        await self.alerter.resolved("schedule-fetch", "Расписание снова доступно.")
        await self.alerter.resolved("schedule-format", "Расписание снова разбирается нормально.")

        if result.total_lessons == 0 and result.had_lessons_before:
            await self.alerter.alert(
                "schedule-empty",
                "Источник вернул пустое расписание на ближайшую неделю, хотя раньше пары были. "
                "Если это не каникулы, возможно, изменился формат.",
            )

        today = self.schedule.today()
        if today in result.changed:
            old, new = result.changed[today]
            await self.notifier.send(await self.notifier.today_changed_text(old, new))
            await self.plan_today()

    @guarded("планирование дня")
    async def plan_today(self) -> None:
        now = datetime.now(self.tz)
        today = now.date()
        for jid in self._today_job_ids:
            try:
                self.scheduler.remove_job(jid)
            except JobLookupError:
                pass
        self._today_job_ids = []

        plan = self.notifier.plan(await self.schedule.lessons_for(today))
        if plan is None:
            log.info("На сегодня очных пар нет, уведомления не планируются")
            return

        n = self.s.notify
        morning_at = plan.first.start - timedelta(minutes=n.morning_minutes_before_first_lesson)
        # Утреннюю сводку, если время прошло, но выход ещё впереди, отправляем сразу
        await self._plan_one("morning", today, morning_at, catch_up_until=plan.leave_at)
        for m in n.leave_reminders_min:
            await self._plan_one(f"remind-{m}", today, plan.leave_at - timedelta(minutes=m))
        await self._plan_one("leave", today, plan.leave_at)
        log.info(
            "План на %s: выход %s, задачи: %s",
            today, plan.leave_at.strftime("%H:%M"), self._today_job_ids,
        )

    async def _plan_one(
        self, kind: str, day: date, run_at: datetime, catch_up_until: datetime | None = None
    ) -> None:
        now = datetime.now(self.tz)
        if await self.db.was_sent(kind, day):
            return
        if run_at <= now:
            if catch_up_until is None or now >= catch_up_until:
                return
            run_at = now + timedelta(seconds=3)
        self.scheduler.add_job(
            self.fire, DateTrigger(run_at, timezone=self.tz), id=kind, args=[kind, day],
            replace_existing=True, misfire_grace_time=180,
        )
        self._today_job_ids.append(kind)

    @guarded("уведомление")
    async def fire(self, kind: str, day: date) -> None:
        """Сработало запланированное уведомление. План пересчитывается по свежему кэшу."""
        if await self.db.was_sent(kind, day):
            return
        plan = self.notifier.plan(await self.schedule.lessons_for(day))
        if plan is None:
            return
        if kind == "morning":
            text = await self.notifier.morning_text()
        elif kind == "leave":
            text = self.notifier.leave_now_text(plan)
        elif kind.startswith("remind-"):
            text = self.notifier.reminder_text(plan, int(kind.split("-", 1)[1]))
        else:
            return
        await self.notifier.send(text)
        await self.db.mark_sent(kind, day)

    @guarded("вечернее сообщение")
    async def evening_job(self) -> None:
        today = self.schedule.today()
        if await self.db.was_sent("evening", today):
            return
        tomorrow = today + timedelta(days=1)
        lessons = await self.schedule.lessons_for(tomorrow)
        if not lessons and not self.s.notify.evening_send_when_no_lessons:
            await self.db.mark_sent("evening", today)
            return
        await self.notifier.send(await self.notifier.tomorrow_text())
        await self.db.mark_sent("evening", today)

    @guarded("очистка заданий")
    async def purge_job(self) -> None:
        n = await self.db.purge_tasks(self.s.notify.tasks_retention_days)
        if n:
            log.info("Удалено просроченных заданий: %d", n)
