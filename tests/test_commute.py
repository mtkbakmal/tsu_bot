from datetime import datetime
from zoneinfo import ZoneInfo

from tsu_bot.commute import build_plan
from tsu_bot.config import CommuteCfg
from tsu_bot.models import Lesson

TZ = ZoneInfo("Asia/Tomsk")


def L(h, m, eh, em, building=2, online=False, title="X"):
    return Lesson(
        start=datetime(2026, 10, 1, h, m, tzinfo=TZ),
        end=datetime(2026, 10, 1, eh, em, tzinfo=TZ),
        title=title, building=None if online else building, room="302", online=online,
    )


def test_basic_plan():
    cfg = CommuteCfg()  # 5 + 3 + 15 + 5 = 28 мин дороги
    plan = build_plan([L(8, 45, 10, 20), L(10, 35, 12, 10)], cfg)
    assert plan.commute_min == 28
    assert plan.leave_at.strftime("%H:%M") == "08:12"  # 08:45 - 28 - 5 запаса
    assert plan.arrive_at.strftime("%H:%M") == "08:40"
    assert plan.wake_at.strftime("%H:%M") == "07:42"  # 08:12 - 10 душ - 5 еда - 15 сборы
    assert plan.last.end.strftime("%H:%M") == "12:10"


def test_first_offline_is_used_when_first_is_online():
    plan = build_plan([L(8, 45, 10, 20, online=True), L(10, 35, 12, 10)], CommuteCfg())
    assert plan.first.start.strftime("%H:%M") == "10:35"


def test_all_online_gives_no_plan():
    assert build_plan([L(8, 45, 10, 20, online=True)], CommuteCfg()) is None


def test_building_specific_walk_and_default():
    cfg = CommuteCfg(walk_from_gate_min={2: 5, 14: 12}, default_walk_from_gate_min=9)
    assert build_plan([L(9, 0, 10, 0, building=14)], cfg).commute_min == 5 + 3 + 15 + 12
    unknown = build_plan([L(9, 0, 10, 0, building=7)], cfg)
    assert unknown.unknown_building and unknown.commute_min == 5 + 3 + 15 + 9
