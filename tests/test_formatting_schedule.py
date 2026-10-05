from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tsu_bot.bot import format_tasks
from tsu_bot.commute import build_plan
from tsu_bot.config import CommuteCfg, ScheduleCfg
from tsu_bot.db import Task
from tsu_bot.formatting import change_summary, day_overview, plural
from tsu_bot.models import Lesson
from tsu_bot.providers.ics import IcsProvider
from tsu_bot.schedule import ScheduleService

from pathlib import Path

TZ = ZoneInfo("Asia/Tomsk")
FIXTURE = Path(__file__).parent / "fixtures" / "schedule.ics"


class FakeCache:
    def __init__(self): self.data = {}
    async def get_days(self, days): return {d: self.data.get(d) for d in days}
    async def save_day(self, day, payload): self.data[day] = payload
    async def delete_days_before(self, day):
        for d in [d for d in self.data if d < day]: del self.data[d]


class FakeProvider:
    def __init__(self, lessons): self.lessons = lessons
    async def fetch(self, a, b): return [l for l in self.lessons if a <= l.start.date() <= b]


def test_plural():
    assert [plural(n, "пара", "пары", "пар") for n in (1, 2, 5, 11, 21)] == ["пара", "пары", "пар", "пар", "пара"]


def test_no_lessons_message():
    assert day_overview("Завтра", [], None, with_wake=True) == \
        "Завтра пар нет, можете отдохнуть или приступить к заданиям."


async def test_tomorrow_text_for_thursday_oct_1():
    svc = ScheduleService(IcsProvider(str(FIXTURE), TZ), FakeCache(),
                          ScheduleCfg(subgroup="б", days_ahead=7), TZ)
    await svc.refresh(today=date(2026, 9, 30))
    lessons = await svc.lessons_for(date(2026, 10, 1))
    text = day_overview("Завтра", lessons, build_plan(lessons, CommuteCfg()), with_wake=True)
    print(text)
    assert lessons[0].start.strftime("%H:%M") == "08:45"
    assert "Завтра 5 пар, первая в 08:45." in text
    assert "Подъём в 07:42, выход в 08:12." in text
    assert "Основы программирования и алгоритмики" in text   # подгруппа «б» 12:25
    assert "онлайн" in text


async def test_change_detection_only_reports_real_changes():
    orig = await IcsProvider(str(FIXTURE), TZ).fetch(date(2026, 10, 1), date(2026, 10, 1))
    cache = FakeCache()
    svc = ScheduleService(FakeProvider(orig), cache, ScheduleCfg(subgroup="б", days_ahead=3), TZ)
    first = await svc.refresh(today=date(2026, 10, 1))
    assert first.changed == {}          # первая загрузка — не «изменение»
    assert (await svc.refresh(today=date(2026, 10, 1))).changed == {}

    moved = [l if l.title != "Дискретная математика" else
             Lesson(**{**l.__dict__, "room": "401"}) for l in orig]
    svc.provider = FakeProvider(moved)
    res = await svc.refresh(today=date(2026, 10, 1))
    assert list(res.changed) == [date(2026, 10, 1)]
    old, new = res.changed[date(2026, 10, 1)]
    text = change_summary(old, new)
    assert "Изменено: 08:45 Дискретная математика, теперь ауд. 401" in text

    svc.provider = FakeProvider([l for l in moved if l.title != "Дискретная математика"])
    text = change_summary(*(await svc.refresh(today=date(2026, 10, 1))).changed[date(2026, 10, 1)])
    assert "Отменено: 08:45 Дискретная математика" in text


def test_format_tasks_structure_and_escaping():
    out = format_tasks([Task(1, "Лаба <1>", "Вариант 5 | сдать\nв четверг"), Task(2, "Эссе", "")])
    assert out == ["<pre>Id|title|description\n1|Лаба &lt;1&gt;|Вариант 5 / сдать в четверг\n2|Эссе|</pre>"]
    assert format_tasks([]) == ["Заданий нет."]


def test_format_tasks_splits_long_lists():
    tasks = [Task(i, "t" * 100, "d" * 200) for i in range(1, 40)]
    chunks = format_tasks(tasks)
    assert len(chunks) > 1 and all(len(c) < 4096 for c in chunks)
    assert all(c.startswith("<pre>Id|title|description") for c in chunks)
