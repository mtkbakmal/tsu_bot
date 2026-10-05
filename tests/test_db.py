"""Интеграционные тесты БД. Нужен TEST_DATABASE_URL, иначе пропускаются."""
import os
from datetime import date

import pytest

from tsu_bot.db import Database

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL не задан")


@pytest.fixture
async def db():
    d = await Database.connect(URL, retries=1)
    await d.init()
    await d.pool.execute("TRUNCATE tasks, schedule_days, sent_notifications RESTART IDENTITY")
    yield d
    await d.close()


async def test_tasks_lifecycle_and_week_retention(db):
    a = await db.add_task("Лаба", "Вариант 5")
    b = await db.add_task("Эссе", "")
    assert (a, b) == (1, 2)
    await db.pool.execute("UPDATE tasks SET created_at = now() - interval '8 days' WHERE id = 1")
    # просроченное не показывается даже до запуска очистки
    assert [t.title for t in await db.list_tasks(7)] == ["Эссе"]
    assert await db.purge_tasks(7) == 1
    assert [t.id for t in await db.list_tasks(7)] == [2]


async def test_schedule_cache_roundtrip(db):
    d1, d2 = date(2026, 10, 1), date(2026, 10, 2)
    await db.save_day(d1, [{"title": "Математика", "x": "ё"}])
    await db.save_day(d1, [{"title": "Обновлено"}])  # upsert
    got = await db.get_days([d1, d2])
    assert got == {d1: [{"title": "Обновлено"}], d2: None}
    await db.delete_days_before(d2)
    assert (await db.get_days([d1]))[d1] is None


async def test_sent_log_is_idempotent(db):
    d = date(2026, 10, 1)
    assert not await db.was_sent("morning", d)
    await db.mark_sent("morning", d)
    await db.mark_sent("morning", d)
    assert await db.was_sent("morning", d) and not await db.was_sent("leave", d)
