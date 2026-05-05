"""Admin commands for filling in missing solutions."""

from __future__ import annotations

import logging
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..config import get_settings
from ..db import Database

log = logging.getLogger(__name__)
router = Router(name="admin")


def _is_admin(user_id: int) -> bool:
    settings = get_settings()
    return user_id in settings.admin_user_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message, db: Database) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только администратору.")
        return
    s = db.stats()
    await message.answer(
        "👑 <b>Админ-панель</b>\n\n"
        f"Глав: {s['chapters']}, параграфов: {s['paragraphs']}\n"
        f"Задач: {s['problems_total']} (с решением: {s['problems_with_solution']}, "
        f"картинок: {s['problems_with_image']})\n\n"
        "<b>Команды:</b>\n"
        "<code>/add НОМЕР текст решения</code> — добавить/обновить решение\n"
        "<code>/setanswer НОМЕР текст ответа</code> — обновить ответ\n"
        "<code>/setstatement НОМЕР текст условия</code> — обновить условие\n"
        "<code>/missing</code> — показать первые 30 задач без решения\n"
        "Для формул используйте LaTeX: <code>\\(x^2\\)</code> для inline и "
        "<code>\\[x^2\\]</code> для блоков.",
        parse_mode="HTML",
    )


_ADD_RE = re.compile(r"^\s*(\d+)\s+(.+)$", re.DOTALL)


def _wrap_paragraph(text: str) -> str:
    """Convert plain user text with blank-line paragraphs into <p>...</p> HTML."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not parts:
        return ""
    return "\n".join(f"<p>{p}</p>" for p in parts)


@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, db: Database) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    args = command.args or ""
    m = _ADD_RE.match(args)
    if not m:
        await message.answer(
            "Формат: <code>/add НОМЕР текст решения</code>",
            parse_mode="HTML",
        )
        return
    berman_number = int(m.group(1))
    body = m.group(2).strip()
    problem = db.get_problem_by_berman_number(berman_number)
    if problem is None:
        await message.answer(f"Задачи №{berman_number} нет в базе. Сначала запустите парсер.")
        return
    db.update_problem_html(berman_number, None, _wrap_paragraph(body), None)
    db._conn.execute(
        "UPDATE problems SET user_added = 1, image_path = NULL, telegram_file_id = NULL "
        "WHERE berman_number = ?",
        (berman_number,),
    )
    await message.answer(
        f"✅ Решение для №{berman_number} сохранено. "
        f"Запустите рендер: <code>python -m berman_bot.renderer --berman {berman_number}</code>",
        parse_mode="HTML",
    )


@router.message(Command("setanswer"))
async def cmd_set_answer(message: Message, command: CommandObject, db: Database) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    args = command.args or ""
    m = _ADD_RE.match(args)
    if not m:
        await message.answer("Формат: <code>/setanswer НОМЕР текст</code>", parse_mode="HTML")
        return
    berman_number = int(m.group(1))
    body = m.group(2).strip()
    if db.get_problem_by_berman_number(berman_number) is None:
        await message.answer(f"Задачи №{berman_number} нет в базе.")
        return
    db.update_problem_html(berman_number, None, None, _wrap_paragraph(body))
    db._conn.execute(
        "UPDATE problems SET image_path = NULL, telegram_file_id = NULL WHERE berman_number = ?",
        (berman_number,),
    )
    await message.answer(f"✅ Ответ для №{berman_number} обновлён.")


@router.message(Command("setstatement"))
async def cmd_set_statement(message: Message, command: CommandObject, db: Database) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    args = command.args or ""
    m = _ADD_RE.match(args)
    if not m:
        await message.answer("Формат: <code>/setstatement НОМЕР текст</code>", parse_mode="HTML")
        return
    berman_number = int(m.group(1))
    body = m.group(2).strip()
    if db.get_problem_by_berman_number(berman_number) is None:
        await message.answer(f"Задачи №{berman_number} нет в базе.")
        return
    db.update_problem_html(berman_number, _wrap_paragraph(body), None, None)
    db._conn.execute(
        "UPDATE problems SET image_path = NULL, telegram_file_id = NULL WHERE berman_number = ?",
        (berman_number,),
    )
    await message.answer(f"✅ Условие для №{berman_number} обновлено.")


@router.message(Command("missing"))
async def cmd_missing(message: Message, db: Database) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    cur = db._conn.execute(
        """
        SELECT berman_number FROM problems
        WHERE has_solution = 0
        ORDER BY berman_number
        LIMIT 30
        """
    )
    rows = [str(r[0]) for r in cur.fetchall()]
    if not rows:
        await message.answer("Нет задач без решения. 🎉")
        return
    await message.answer("Первые 30 задач без решения: " + ", ".join(rows))
