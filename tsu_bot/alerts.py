"""Служебные уведомления владельцу: сломался парсер, недоступен сайт, упала задача."""
from __future__ import annotations

import logging
import time
from html import escape

from aiogram import Bot

log = logging.getLogger(__name__)


class Alerter:
    def __init__(self, bot: Bot, owner_id: int, cooldown_min: int = 360) -> None:
        self.bot = bot
        self.owner_id = owner_id
        self.cooldown = cooldown_min * 60
        self._last: dict[str, float] = {}
        self._active: set[str] = set()

    async def alert(self, key: str, text: str) -> None:
        """Не чаще одного раза за cooldown на ключ."""
        now = time.monotonic()
        self._active.add(key)
        if now - self._last.get(key, -self.cooldown) < self.cooldown:
            return
        self._last[key] = now
        await self._send(f"Проблема в сервисе.\n{escape(text)}")

    async def resolved(self, key: str, text: str) -> None:
        if key in self._active:
            self._active.discard(key)
            self._last.pop(key, None)
            await self._send(escape(text))

    async def _send(self, text: str) -> None:
        try:
            await self.bot.send_message(self.owner_id, text)
        except Exception:  # Telegram недоступен: остаётся только лог
            log.exception("Не удалось отправить служебное сообщение")
