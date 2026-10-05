from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tsu_bot.parsing import for_subgroup, parse_location, parse_summary
from tsu_bot.providers.ics import IcsProvider, parse_ics

TZ = ZoneInfo("Asia/Tomsk")
FIXTURE = Path(__file__).parent / "fixtures" / "schedule.ics"


@pytest.mark.parametrize(
    "summary,expected",
    [
        ("Основы программирования и алгоритмики, (932603)", ("Основы программирования и алгоритмики", None)),
        ("Основы программирования и алгоритмики, (932603 (а))", ("Основы программирования и алгоритмики", "а")),
        ("Иностранный язык (Английский язык), (932603 (Б))", ("Иностранный язык (Английский язык)", "б")),
        ("Без группы", ("Без группы", None)),
    ],
)
def test_parse_summary(summary, expected):
    assert parse_summary(summary) == expected


@pytest.mark.parametrize(
    "loc,expected",
    [
        ("302 (2) Учебная аудитория", ("302", 2, "Учебная аудитория", False)),
        ("212а (2) Компьютерный класс", ("212а", 2, "Компьютерный класс", False)),
        ("013 (2) Учебная аудитория ", ("013", 2, "Учебная аудитория", False)),
        ("Спортивный зал 93 (14)", ("Спортивный зал 93", 14, "", False)),
        ("Онлайн", ("", None, "", True)),
    ],
)
def test_parse_location(loc, expected):
    assert parse_location(loc) == expected


def test_ics_times_are_converted_to_tomsk():
    lessons = parse_ics(FIXTURE.read_bytes(), TZ)
    assert len(lessons) == 18
    first = lessons[0]
    assert first.start.strftime("%Y-%m-%d %H:%M") == "2026-09-28 08:45"  # 01:45Z + 7ч
    assert first.end.strftime("%H:%M") == "10:20"
    assert first.teacher == "Костюк Юрий Леонидович"


async def test_subgroup_b_filter():
    lessons = await IcsProvider(str(FIXTURE), TZ).fetch(date(2026, 9, 28), date(2026, 10, 4))
    mine = for_subgroup(lessons, "б")
    # 18 в файле: 2 пары подгруппы «а» отпадают
    assert len(lessons) == 18
    assert len(mine) == 16
    assert all(l.subgroup in (None, "б") for l in mine)
    day29 = [l.title for l in mine if l.start.date() == date(2026, 9, 29)]
    assert not any("Английский" in t for t in day29)  # английский 29-го у подгруппы «а»
    day30 = [l.title for l in mine if l.start.date() == date(2026, 9, 30)]
    assert any("Английский" in t for t in day30)  # а 30-го у «б»


async def test_online_and_gym_flags():
    lessons = await IcsProvider(str(FIXTURE), TZ).fetch(date(2026, 10, 1), date(2026, 10, 2))
    online = [l for l in lessons if l.online]
    assert {l.title for l in online} == {"Архитектура вычислительных систем", "Введение в специальность"}
    gym = [l for l in lessons if l.building == 14]
    assert len(gym) == 1 and gym[0].room == "Спортивный зал 93"


async def test_subgroup_a_filter():
    lessons = await IcsProvider(str(FIXTURE), TZ).fetch(date(2026, 9, 28), date(2026, 10, 4))
    a = for_subgroup(lessons, "а")
    b = for_subgroup(lessons, "б")
    assert all(l.subgroup in (None, "а") for l in a)
    common = [l for l in lessons if l.subgroup is None]
    only_a = [l for l in lessons if l.subgroup == "а"]
    only_b = [l for l in lessons if l.subgroup == "б"]
    assert len(a) == len(common) + len(only_a) and len(b) == len(common) + len(only_b)
    assert len(only_a) + len(only_b) + len(common) == len(lessons)
    # английский 29-го у подгруппы «а», 30-го у «б»
    assert any("Английский" in l.title and l.start.date() == date(2026, 9, 29) for l in a)
    assert not any("Английский" in l.title and l.start.date() == date(2026, 9, 30) for l in a)
