"""Telegram-бот: клавиатура из трёх кнопок, доступ только владельцу."""
from __future__ import annotations

import logging
from html import escape

from aiogram import BaseMiddleware, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from .db import Database, Task
from .notifier import Notifier
from .providers import ScheduleFetchError, ScheduleFormatError

log = logging.getLogger(__name__)

BTN_TOMORROW = "Что завтра?"
BTN_ADD = "Добавить задание"
BTN_LIST = "Просмотреть задания"

TITLE_MAX = 200
DESC_MAX = 2000
CHUNK_MAX = 3500  # лимит Telegram 4096 с запасом на теги


class AddTask(StatesGroup):
    title = State()
    description = State()


def keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TOMORROW)],
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_LIST)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


class OwnerOnly(BaseMiddleware):
    def __init__(self, owner_id: int) -> None:
        self.owner_id = owner_id

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.id != self.owner_id:
            log.warning("Игнорирую сообщение от чужого пользователя %s", getattr(user, "id", None))
            return None
        return await handler(event, data)


def _cell(text: str) -> str:
    """Значение ячейки таблицы: без переводов строк и разделителя."""
    return " ".join(text.split()).replace("|", "/")


def format_tasks(tasks: list[Task]) -> list[str]:
    """Id|title|description, моноширинным блоком; длинный список режется на сообщения."""
    if not tasks:
        return ["Заданий нет."]
    header = "Id|title|description"
    rows = [f"{t.id}|{_cell(t.title)}|{_cell(t.description)}" for t in tasks]
    chunks: list[list[str]] = [[]]
    size = len(header)
    for row in rows:
        if size + len(row) + 1 > CHUNK_MAX and chunks[-1]:
            chunks.append([])
            size = len(header)
        chunks[-1].append(row)
        size += len(row) + 1
    return [f"<pre>{escape(header + chr(10) + chr(10).join(c))}</pre>" for c in chunks]


def build_dispatcher(owner_id: int, notifier: Notifier, db: Database, retention_days: int) -> Dispatcher:
    router = Router()
    router.message.outer_middleware(OwnerOnly(owner_id))

    @router.message(CommandStart())
    async def start(m: Message, state: FSMContext) -> None:
        await state.clear()
        await m.answer("Готово. Кнопки внизу.", reply_markup=keyboard())

    # Кнопки меню регистрируются раньше состояний: нажатие кнопки всегда отменяет ввод задания.
    @router.message(F.text == BTN_TOMORROW)
    async def tomorrow(m: Message, state: FSMContext) -> None:
        await state.clear()
        try:
            text = await notifier.tomorrow_text()
        except (ScheduleFetchError, ScheduleFormatError) as e:
            log.warning("Что завтра: %s", e)
            text = "Не удалось получить расписание, попробуйте позже."
        await m.answer(text, reply_markup=keyboard())

    @router.message(F.text == BTN_ADD)
    async def add_start(m: Message, state: FSMContext) -> None:
        await state.set_state(AddTask.title)
        await m.answer("Название задания?", reply_markup=keyboard())

    @router.message(F.text == BTN_LIST)
    async def list_tasks(m: Message, state: FSMContext) -> None:
        await state.clear()
        for chunk in format_tasks(await db.list_tasks(retention_days)):
            await m.answer(chunk, reply_markup=keyboard())

    @router.message(AddTask.title, F.text)
    async def add_title(m: Message, state: FSMContext) -> None:
        title = (m.text or "").strip()[:TITLE_MAX]
        if not title:
            await m.answer("Название не может быть пустым. Название задания?")
            return
        await state.update_data(title=title)
        await state.set_state(AddTask.description)
        await m.answer("Описание? Отправьте «-», если не нужно.")

    @router.message(AddTask.description, F.text)
    async def add_description(m: Message, state: FSMContext) -> None:
        data = await state.get_data()
        text = (m.text or "").strip()
        description = "" if text == "-" else text[:DESC_MAX]
        task_id = await db.add_task(data["title"], description)
        await state.clear()
        await m.answer(f"Задание добавлено, id {task_id}.", reply_markup=keyboard())

    @router.message()
    async def fallback(m: Message) -> None:
        await m.answer("Выберите действие на клавиатуре.", reply_markup=keyboard())

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    return dp
