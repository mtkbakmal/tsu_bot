"""Тексты сообщений (Telegram parse_mode=HTML, поэтому всё динамическое экранируется)."""
from __future__ import annotations

from html import escape

from .clothing import Advice, precip_kind
from .commute import DayPlan
from .models import Lesson
from .weather import Hour


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def hhmm(dt) -> str:
    return dt.strftime("%H:%M")


def fmt_t(v: float) -> str:
    r = int(round(v))
    return f"{r:+d}°" if r else "0°"


def room_text(l: Lesson) -> str:
    if l.online:
        return "онлайн"
    parts = []
    if l.room:
        parts.append(f"ауд. {l.room}" if l.room[0].isdigit() else l.room)
    if l.building is not None:
        parts.append(f"корпус {l.building}")
    text = ", ".join(parts)
    if l.room_kind and l.room_kind.lower() != "учебная аудитория":
        text += f" ({l.room_kind.lower()})"
    return text


def lesson_list(lessons: list[Lesson]) -> str:
    out = []
    for i, l in enumerate(lessons, 1):
        title = escape(l.title)
        if l.lesson_type:
            title += f" — {escape(l.lesson_type)}"
        out.append(f"{i}. {hhmm(l.start)}–{hhmm(l.end)} {title}")
        details = "; ".join(p for p in (escape(l.teacher), escape(room_text(l))) if p)
        if details:
            out.append(f"    {details}")
    return "\n".join(out)


def day_overview(
    word: str, lessons: list[Lesson], plan: DayPlan | None, *, with_wake: bool
) -> str:
    """word: 'Сегодня' | 'Завтра'."""
    if not lessons:
        return f"{word} пар нет, можете отдохнуть или приступить к заданиям."

    n = len(lessons)
    lines = [f"{word} {n} {plural(n, 'пара', 'пары', 'пар')}, первая в {hhmm(lessons[0].start)}."]
    if plan is None:
        lines.append("Все пары онлайн, выходить из общежития не нужно.")
    else:
        if plan.first is not lessons[0]:
            lines.append(f"Первая очная пара в {hhmm(plan.first.start)}.")
        timing = f"Выход в {hhmm(plan.leave_at)}"
        if with_wake:
            timing = f"Подъём в {hhmm(plan.wake_at)}, выход в {hhmm(plan.leave_at)}"
        lines.append(
            f"{timing}. Дорога {plan.commute_min} мин, на месте к {hhmm(plan.arrive_at)}."
        )
        if plan.unknown_building:
            b = f"корпус {plan.building}" if plan.building is not None else "корпус не указан"
            lines.append(
                f"({b}: время пешком не задано в конфиге, взято {plan.walk_from_gate_min} мин.)"
            )
    return "\n".join(lines) + "\n\n" + lesson_list(lessons)


def weather_block(points: list[tuple[str, Hour]], advice: Advice) -> str:
    lines = ["Погода"]
    for label, h in points:
        kind = precip_kind(h) or "без осадков"
        lines.append(
            f"{label}: {fmt_t(h.temp)}, ощущается {fmt_t(h.feels)}, "
            f"ветер {h.wind:.0f} м/с, {kind}."
        )
    if len(points) == 2:
        drop = points[0][1].feels - points[1][1].feels
        if drop >= 4:
            lines.append(f"К концу пар похолодает на {drop:.0f}°.")
    lines.append(f"Одежда: {advice.layers}.")
    lines.append(f"Обувь: {advice.shoes}.")
    if advice.accessories:
        lines.append("Взять: " + ", ".join(advice.accessories) + ".")
    for w in advice.warnings:
        lines.append(f"Внимание: {w}.")
    return "\n".join(escape(x, quote=False) for x in lines)


def diff_lessons(
    old: list[Lesson], new: list[Lesson]
) -> tuple[list[Lesson], list[Lesson], list[Lesson]]:
    """-> (отменены, добавлены, изменены). Пара опознаётся по (время начала, название)."""
    ok = {(l.start, l.title): l for l in old}
    nk = {(l.start, l.title): l for l in new}
    removed = [ok[k] for k in ok if k not in nk]
    added = [nk[k] for k in nk if k not in ok]
    changed = [nk[k] for k in nk if k in ok and ok[k] != nk[k]]
    return removed, added, changed


def change_summary(old: list[Lesson], new: list[Lesson]) -> str:
    removed, added, changed = diff_lessons(old, new)
    lines = ["Расписание на сегодня изменилось."]

    def short(l: Lesson) -> str:
        return f"{hhmm(l.start)} {escape(l.title)}"

    for l in removed:
        lines.append(f"Отменено: {short(l)}")
    for l in added:
        lines.append(f"Добавлено: {short(l)}, {escape(room_text(l))}")
    for l in changed:
        lines.append(f"Изменено: {short(l)}, теперь {escape(room_text(l))}")
    return "\n".join(lines)
