"""Тесты разбора JSON API InTime. Фикстура — фрагмент реального ответа за 30.09.2026."""
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tsu_bot.parsing import for_subgroup
from tsu_bot.providers import ScheduleFormatError
from tsu_bot.providers.ics import parse_ics
from tsu_bot.providers.intime_api import payload_to_lessons

TZ = ZoneInfo("Asia/Tomsk")
GROUP = "8d02325c-8b15-11f1-9de8-6cb3110a6d8e"
BUILDING = {"name": "2 корпус", "address": "пр. Ленина, 36к2"}


def g(name, sub, gid=GROUP):
    return {"id": gid, "name": name, "isSubgroup": sub, "facultyId": "f"}


def lesson(title, lt, groups, prof, aud, starts, ends, n):
    return {"type": "LESSON", "id": "x", "title": title, "lessonType": lt, "groups": groups,
            "professor": {"id": "p", "fullName": prof},
            "audience": aud, "lessonNumber": n, "starts": starts, "ends": ends}


def aud(name):
    return {"id": "a", "name": name, "shortName": name.split(" ", 1)[0], "building": BUILDING}


def empty(n, s, e):
    return {"type": "EMPTY", "starts": s, "ends": e, "lessonNumber": n}


REAL = {"grid": [{"date": "2026-09-30", "lessons": [
    empty(1, 6300, 12000),
    lesson("История России", "LECTURE", [g("932603", False)], "Морев Владимир Алексеевич",
           aud("302 (2) Учебная аудитория"), 12900, 18600, 2),
    lesson("Иностранный язык (Английский язык)", "SEMINAR", [g("932603 (б)", True)],
           "Селиванов Денис Владимирович", aud("114 (2) Учебная аудитория"), 19500, 25200, 3),
    empty(4, 27900, 33600), empty(5, 34500, 40200),
]}]}


def test_real_payload_skips_empty_slots_and_parses_fields():
    hist, eng = payload_to_lessons(REAL, TZ, GROUP)
    assert hist.start.strftime("%Y-%m-%d %H:%M") == "2026-09-30 10:35"   # 12900 c от полуночи UTC + 7ч
    assert hist.end.strftime("%H:%M") == "12:10"
    assert (hist.title, hist.lesson_type, hist.subgroup) == ("История России", "лекция", None)
    assert hist.teacher == "Морев Владимир Алексеевич"
    assert (hist.room, hist.building, hist.room_kind) == ("302", 2, "Учебная аудитория")
    assert (eng.lesson_type, eng.subgroup, eng.room) == ("семинар", "б", "114")


def test_matches_ics_export_for_same_day():
    """API и ICS-экспорт должны давать одни и те же время и аудитории."""
    ics = [l for l in parse_ics((Path(__file__).parent / "fixtures" / "schedule.ics").read_bytes(), TZ)
           if l.start.date() == date(2026, 9, 30)]
    api = payload_to_lessons(REAL, TZ, GROUP)
    assert [(l.start, l.end, l.room, l.building, l.teacher, l.subgroup) for l in api] == \
           [(l.start, l.end, l.room, l.building, l.teacher, l.subgroup) for l in ics]


def test_subgroup_filter_on_api_lessons():
    a = lesson("Программирование", "LABORATORY", [g("932603 (а)", True)], "П", aud("212а (2) Компьютерный класс"), 1, 2, 1)
    b = lesson("Программирование", "LABORATORY", [g("932603 (б)", True)], "П", aud("212а (2) Компьютерный класс"), 3, 4, 1)
    both = lesson("Физика", "PRACTICE", [g("932603 (а)", True), g("932603 (б)", True)], "П", aud("1 (2)"), 5, 6, 1)
    payload = {"grid": [{"date": "2026-10-01", "lessons": [a, b, both]}]}
    lessons = payload_to_lessons(payload, TZ, GROUP)
    assert [l.subgroup for l in lessons] == ["а", "б", None]
    assert [l.lesson_type for l in lessons] == ["лабораторная", "лабораторная", "практика"]
    assert len(for_subgroup(lessons, "б")) == 2


def test_stream_lecture_with_several_groups_is_common():
    other = "other-group-id"
    l = lesson("Лекция потока", "LECTURE", [g("932601", False, other), g("932603", False)], "П", aud("1 (2)"), 1, 2, 1)
    (res,) = payload_to_lessons({"grid": [{"date": "2026-10-01", "lessons": [l]}]}, TZ, GROUP)
    assert res.subgroup is None


def test_online_and_missing_audience():
    on = lesson("Архитектура", "LECTURE", [g("932603", False)], "П", {"name": "Онлайн"}, 1, 2, 1)
    none = lesson("Что-то", "LECTURE", [g("932603", False)], "П", None, 3, 4, 2)
    a, b = payload_to_lessons({"grid": [{"date": "2026-10-01", "lessons": [on, none]}]}, TZ, GROUP)
    assert a.online and a.building is None
    assert not b.online and b.room == "" and b.building is None


def test_unknown_lesson_type_is_kept_lowercase():
    l = lesson("X", "WEBINAR", [g("932603", False)], "П", aud("1 (2)"), 1, 2, 1)
    (res,) = payload_to_lessons({"grid": [{"date": "2026-10-01", "lessons": [l]}]}, TZ, GROUP)
    assert res.lesson_type == "webinar"


@pytest.mark.parametrize("payload", [{}, [], {"grid": {}}, {"grid": [{"date": "2026-10-01"}]},
                                     {"grid": [{"date": "bad", "lessons": []}]},
                                     {"grid": [{"date": "2026-10-01", "lessons": [{"type": "LESSON", "starts": 1, "ends": 2}]}]}])
def test_format_drift_raises_instead_of_returning_garbage(payload):
    with pytest.raises(ScheduleFormatError):
        payload_to_lessons(payload, TZ, GROUP)
