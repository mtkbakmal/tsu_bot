"""Точка входа: python -m tsu_bot"""
from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError

from .alerts import Alerter
from .bot import build_dispatcher
from .config import load_settings
from .db import Database
from .notifier import Notifier
from .planner import Planner
from .providers import build_provider
from .schedule import ScheduleService
from .weather import WeatherClient

log = logging.getLogger("tsu_bot")


async def poll_forever(dp, bot, *, first_delay=10.0, max_delay=120.0, sleep=asyncio.sleep) -> None:
    """Long polling с повторами, если Telegram недоступен при старте.

    Без этого процесс падал бы при каждой недоступности api.telegram.org, а контейнер
    уходил бы в цикл перезапусков. Планировщик всё это время продолжает работать.
    """
    delay = first_delay
    while True:
        try:
            await dp.start_polling(bot, close_bot_session=False)
            return
        except TelegramNetworkError as e:
            log.warning("Telegram недоступен (%s). Повтор через %.0f с", e, delay)
            await sleep(delay)
            delay = min(delay * 2, max_delay)


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.env.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    tz = ZoneInfo(settings.schedule.timezone)

    db = await Database.connect(settings.env.database_url)
    await db.init()

    schedule = ScheduleService(build_provider(settings.schedule, tz), db, settings.schedule, tz)
    weather = WeatherClient(settings.weather, tz)
    proxy = settings.env.telegram_proxy.strip() or None
    if proxy:
        log.info("Telegram: используется прокси")
    bot = Bot(
        token=settings.env.telegram_bot_token,
        session=AiohttpSession(proxy=proxy),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    notifier = Notifier(bot, settings, schedule, weather, tz)
    alerter = Alerter(bot, settings.env.telegram_owner_id)
    planner = Planner(settings, db, schedule, notifier, alerter, tz)
    dp = build_dispatcher(
        settings.env.telegram_owner_id, notifier, db, settings.notify.tasks_retention_days
    )

    planner.start()
    startup_task = asyncio.create_task(planner.startup())  # не блокирует запуск бота
    log.info("Сервис запущен (источник расписания: %s)", settings.schedule.source)
    try:
        await poll_forever(dp, bot)
    finally:
        startup_task.cancel()
        planner.shutdown()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
