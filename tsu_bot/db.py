"""PostgreSQL: задания, кэш расписания, журнал отправленных уведомлений."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date

import asyncpg

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tasks_created_at_idx ON tasks (created_at);

CREATE TABLE IF NOT EXISTS schedule_days (
    day        DATE PRIMARY KEY,
    payload    JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sent_notifications (
    kind    TEXT NOT NULL,
    day     DATE NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, day)
);
"""


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    description: str


class Database:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, url: str, *, retries: int = 30, delay: float = 2.0) -> "Database":
        """Ждёт, пока Postgres поднимется (удобно при старте через docker compose)."""
        for attempt in range(1, retries + 1):
            try:
                pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
                return cls(pool)
            except (OSError, asyncpg.PostgresError, asyncpg.CannotConnectNowError) as e:
                if attempt == retries:
                    raise
                log.warning("БД недоступна (%s), попытка %d/%d", e, attempt, retries)
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")

    async def init(self) -> None:
        async with self.pool.acquire() as c:
            await c.execute(SCHEMA)

    async def close(self) -> None:
        await self.pool.close()

    # --- задания ---------------------------------------------------------

    async def add_task(self, title: str, description: str) -> int:
        return await self.pool.fetchval(
            "INSERT INTO tasks (title, description) VALUES ($1, $2) RETURNING id",
            title,
            description,
        )

    async def list_tasks(self, retention_days: int) -> list[Task]:
        rows = await self.pool.fetch(
            "SELECT id, title, description FROM tasks "
            "WHERE created_at >= now() - make_interval(days => $1) ORDER BY id",
            retention_days,
        )
        return [Task(r["id"], r["title"], r["description"]) for r in rows]

    async def purge_tasks(self, retention_days: int) -> int:
        res = await self.pool.execute(
            "DELETE FROM tasks WHERE created_at < now() - make_interval(days => $1)",
            retention_days,
        )
        return int(res.split()[-1])

    # --- кэш расписания (ScheduleCache) -----------------------------------

    async def get_days(self, days: list[date]) -> dict[date, list[dict] | None]:
        rows = await self.pool.fetch(
            "SELECT day, payload::text AS payload FROM schedule_days WHERE day = ANY($1::date[])",
            days,
        )
        found = {r["day"]: json.loads(r["payload"]) for r in rows}
        return {d: found.get(d) for d in days}

    async def save_day(self, day: date, payload: list[dict]) -> None:
        await self.pool.execute(
            "INSERT INTO schedule_days (day, payload) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (day) DO UPDATE SET payload = EXCLUDED.payload, fetched_at = now()",
            day,
            json.dumps(payload, ensure_ascii=False),
        )

    async def delete_days_before(self, day: date) -> None:
        await self.pool.execute("DELETE FROM schedule_days WHERE day < $1", day)
        await self.pool.execute("DELETE FROM sent_notifications WHERE day < $1", day)

    # --- журнал уведомлений -----------------------------------------------

    async def was_sent(self, kind: str, day: date) -> bool:
        return bool(
            await self.pool.fetchval(
                "SELECT 1 FROM sent_notifications WHERE kind = $1 AND day = $2", kind, day
            )
        )

    async def mark_sent(self, kind: str, day: date) -> None:
        await self.pool.execute(
            "INSERT INTO sent_notifications (kind, day) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            kind,
            day,
        )
