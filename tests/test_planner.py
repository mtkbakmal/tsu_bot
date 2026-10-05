from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import tsu_bot.planner as planner_mod
from tsu_bot.commute import build_plan
from tsu_bot.config import Settings, ScheduleCfg, CommuteCfg, NotifyCfg, WeatherCfg, Env
from tsu_bot.planner import Planner
from tsu_bot.providers import ScheduleFetchError, ScheduleFormatError
from tsu_bot.providers.ics import IcsProvider
from tsu_bot.schedule import ScheduleService

TZ = ZoneInfo("Asia/Tomsk")
FIXTURE = Path(__file__).parent / "fixtures" / "schedule.ics"


class FakeDB:
    def __init__(self):
        self.days, self.sent = {}, set()
    async def get_days(self, days): return {d: self.days.get(d) for d in days}
    async def save_day(self, day, payload): self.days[day] = payload
    async def delete_days_before(self, day): pass
    async def was_sent(self, kind, day): return (kind, day) in self.sent
    async def mark_sent(self, kind, day): self.sent.add((kind, day))


class FakeNotifier:
    def __init__(self, commute): self.commute, self.sent = commute, []
    def plan(self, lessons): return build_plan(lessons, self.commute)
    async def send(self, text): self.sent.append(text)


class FakeAlerter:
    def __init__(self): self.alerts, self.ok = [], []
    async def alert(self, key, text): self.alerts.append(key)
    async def resolved(self, key, text): self.ok.append(key)


def freeze(monkeypatch, y, mo, d, h, mi):
    frozen = datetime(y, mo, d, h, mi, tzinfo=TZ)

    class FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None): return frozen.astimezone(tz) if tz else frozen

    monkeypatch.setattr(planner_mod, "datetime", FrozenDT)


async def make(monkeypatch=None):
    settings = Settings(
        env=Env(telegram_bot_token="1:x", telegram_owner_id=1, database_url="postgresql://x"),
        schedule=ScheduleCfg(subgroup="б"), commute=CommuteCfg(), notify=NotifyCfg(), weather=WeatherCfg(),
    )
    db = FakeDB()
    svc = ScheduleService(IcsProvider(str(FIXTURE), TZ), db, settings.schedule, TZ)
    await svc.refresh(today=date(2026, 9, 30))
    alerter = FakeAlerter()
    p = Planner(settings, db, svc, FakeNotifier(settings.commute), alerter, TZ)
    return p, db, svc, alerter


def job_times(p):
    return {j.id: j.trigger.run_date.astimezone(TZ).strftime("%H:%M") for j in p.scheduler.get_jobs()
            if j.id in ("morning", "leave") or j.id.startswith("remind-")}


async def test_plans_all_notifications_before_first_lesson(monkeypatch):
    p, *_ = await make()
    freeze(monkeypatch, 2026, 10, 1, 6, 30)   # первая пара 08:45, выход 08:12
    await p.plan_today()
    assert job_times(p) == {"morning": "07:45", "remind-15": "07:57", "leave": "08:12"}


async def test_morning_catch_up_after_restart(monkeypatch):
    p, *_ = await make()
    freeze(monkeypatch, 2026, 10, 1, 8, 0)    # сводка (07:45) пропущена, выход (08:12) ещё впереди
    await p.plan_today()
    times = job_times(p)
    assert times["morning"] == "08:00" and times["leave"] == "08:12" and "remind-15" not in times


async def test_nothing_planned_after_leave_time_or_if_already_sent(monkeypatch):
    p, db, *_ = await make()
    freeze(monkeypatch, 2026, 10, 1, 9, 0)
    await p.plan_today()
    assert job_times(p) == {}
    freeze(monkeypatch, 2026, 10, 1, 6, 30)
    await db.mark_sent("morning", date(2026, 10, 1))
    await p.plan_today()
    assert "morning" not in job_times(p)


async def test_no_offline_lessons_means_no_jobs(monkeypatch):
    p, *_ = await make()
    freeze(monkeypatch, 2026, 9, 27, 6, 0)    # воскресенье, пар нет
    await p.plan_today()
    assert job_times(p) == {}


async def test_source_errors_alert_correctly():
    p, _, svc, alerter = await make()

    async def boom_fetch(*a): raise ScheduleFetchError("down")
    async def boom_format(*a): raise ScheduleFormatError("bad json")
    svc.provider.fetch = boom_fetch
    for _ in range(2): await p.refresh_job()
    assert alerter.alerts == []                       # пока это может быть кратковременный сбой
    await p.refresh_job()
    assert alerter.alerts == ["schedule-fetch"]       # третий подряд: сообщаем
    svc.provider.fetch = boom_format
    await p.refresh_job()
    assert alerter.alerts[-1] == "schedule-format"    # смена формата: сразу
