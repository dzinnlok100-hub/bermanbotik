"""/start and /help commands."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .. import keyboards
from ..db import Database

router = Router(name="start")


HELLO_TEXT = (
    "👋 <b>Решебник Бермана</b>\n"
    "<i>Сборник задач по курсу математического анализа</i>\n\n"
    "Что я умею:\n"
    "• 📚 Открыть оглавление: /menu\n"
    "• 🔢 Просто пришлите номер задачи (например, <code>123</code>) — пришлю её решение.\n"
    "• 🎲 Случайная задача с решением: /random\n"
    "• ❓ Помощь: /help\n\n"
    "Источник решений: <a href=\"https://amkbook.net/problem/source/1\">amkbook.net</a>."
)


HELP_TEXT = (
    "<b>Команды:</b>\n"
    "/start — приветствие\n"
    "/menu — оглавление (главы → параграфы → задачи)\n"
    "/random — случайная задача с решением\n"
    "/stats — сколько задач уже в базе\n\n"
    "<b>Поиск по номеру:</b> просто отправьте число.\n"
    "Например: <code>1234</code>\n\n"
    "Если решения нет — бот так и скажет, и предложит ссылку на источник или альтернативный сборник."
)


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    if message.from_user:
        db.touch_user(message.from_user.id, message.from_user.username)
    await message.answer(
        HELLO_TEXT,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=keyboards.main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("menu"))
async def cmd_menu(message: Message, db: Database) -> None:
    chapters = db.list_chapters()
    if not chapters:
        await message.answer(
            "База пока пуста. Запустите парсер: <code>python -m berman_bot.parser</code>.",
            parse_mode="HTML",
        )
        return
    await message.answer(
        "📚 <b>Главы сборника:</b>",
        parse_mode="HTML",
        reply_markup=keyboards.chapters_kb(chapters),
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database) -> None:
    s = db.stats()
    await message.answer(
        "📊 <b>Статистика базы</b>\n"
        f"Главы: <b>{s['chapters']}</b>\n"
        f"Параграфы: <b>{s['paragraphs']}</b>\n"
        f"Задачи всего: <b>{s['problems_total']}</b>\n"
        f"С решением: <b>{s['problems_with_solution']}</b>\n"
        f"Отрендерено картинок: <b>{s['problems_with_image']}</b>",
        parse_mode="HTML",
    )
