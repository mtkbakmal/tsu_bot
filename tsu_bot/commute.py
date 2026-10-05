"""Расчёт времени выхода и подъёма по средним значениям."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import CommuteCfg
from .models import Lesson


@dataclass(frozen=True)
class DayPlan:
    lessons: list[Lesson]
    first: Lesson  # первая очная пара
    last: Lesson  # последняя очная пара (по времени окончания)
    building: int | None
    commute_min: int
    walk_from_gate_min: int
    unknown_building: bool  # время пешком не задано в конфиге, взято значение по умолчанию
    leave_at: datetime
    arrive_at: datetime
    wake_at: datetime


def build_plan(lessons: list[Lesson], cfg: CommuteCfg) -> DayPlan | None:
    """План по первой очной паре дня. Онлайн-пары не требуют дороги.

    None, если очных пар нет.
    """
    offline = sorted((l for l in lessons if not l.online), key=lambda l: l.start)
    if not offline:
        return None
    first = offline[0]
    last = max(offline, key=lambda l: l.end)

    walk = cfg.walk_from_gate_min.get(first.building) if first.building is not None else None
    unknown = walk is None
    if walk is None:
        walk = cfg.default_walk_from_gate_min

    commute = cfg.walk_to_stop_min + cfg.bus_wait_min + cfg.bus_ride_min + walk
    leave_at = first.start - timedelta(minutes=commute + cfg.safety_margin_min)
    return DayPlan(
        lessons=lessons,
        first=first,
        last=last,
        building=first.building,
        commute_min=commute,
        walk_from_gate_min=walk,
        unknown_building=unknown,
        leave_at=leave_at,
        arrive_at=leave_at + timedelta(minutes=commute),
        wake_at=leave_at
        - timedelta(minutes=cfg.shower_min + cfg.eating_min + cfg.wake_extra_min),
    )
