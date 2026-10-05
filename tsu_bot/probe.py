"""Проверка источника расписания: python -m tsu_bot.probe

Показывает сырой ответ InTime API и то, как он разобрался. Нужен один раз, чтобы
убедиться, что путь эндпоинта и ключи JSON подходят (см. tsu_bot/providers/intime_api.py).
Не требует токена и БД.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .config import ScheduleCfg
from .parsing import for_subgroup
from .providers import ScheduleFetchError, ScheduleFormatError
from .providers.intime_api import InTimeApiProvider, payload_to_lessons


async def main() -> None:
    path = Path(os.environ.get("CONFIG_PATH", "config.yaml"))
    cfg = ScheduleCfg(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("schedule", {}))
    tz = ZoneInfo(cfg.timezone)
    provider = InTimeApiProvider(cfg, tz)
    today = datetime.now(tz).date()
    end = today + timedelta(days=6)
    print("URL:", provider.url(today, end))

    try:
        payload = await provider.fetch_raw(today, end)
    except (ScheduleFetchError, ScheduleFormatError) as e:
        print("ОШИБКА запроса:", e)
        print("Откройте страницу расписания, во вкладке Network (DevTools) найдите запрос с "
              "расписанием и поправьте api_url_template в config.yaml.")
        return

    print("\n--- сырой ответ (начало) ---")
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:3000])

    print("\n--- разбор ---")
    try:
        lessons = payload_to_lessons(payload, tz, cfg.group_id)
    except ScheduleFormatError as e:
        print("ОШИБКА разбора:", e)
        print("Поправьте списки ключей в tsu_bot/providers/intime_api.py под ответ выше.")
        return
    mine = for_subgroup(lessons, cfg.subgroup)
    print(f"Всего пар: {len(lessons)}, для подгруппы «{cfg.subgroup}»: {len(mine)}")
    for l in mine[:8]:
        print(f"  {l.start:%a %d.%m %H:%M}-{l.end:%H:%M} | {l.title} | {l.lesson_type} | "
              f"{l.teacher} | ауд. {l.room}, корпус {l.building}, онлайн={l.online}")
    if not lessons:
        print("Пар не найдено: скорее всего, ключи не совпали с ответом.")


if __name__ == "__main__":
    asyncio.run(main())
