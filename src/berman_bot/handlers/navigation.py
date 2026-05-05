"""Inline-keyboard navigation: chapters → paragraphs → problems → problem card."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    Message,
)

from .. import keyboards
from ..db import Database, Problem

log = logging.getLogger(__name__)
router = Router(name="navigation")


# ---- callback: menu chapters -------------------------------------------------


@router.callback_query(F.data == "menu:chapters")
async def cb_chapters(query: CallbackQuery, db: Database) -> None:
    chapters = db.list_chapters()
    text = "📚 <b>Главы сборника:</b>"
    markup = keyboards.chapters_kb(chapters)
    await _safe_edit(query, text, markup)


@router.callback_query(F.data == "help")
async def cb_help(query: CallbackQuery) -> None:
    from .start import HELP_TEXT

    await _safe_edit(query, HELP_TEXT, None)


@router.callback_query(F.data == "noop")
async def cb_noop(query: CallbackQuery) -> None:
    await query.answer()


# ---- callback: chapter -------------------------------------------------------


@router.callback_query(F.data.startswith("ch:"))
async def cb_chapter(query: CallbackQuery, db: Database) -> None:
    assert query.data is not None
    chapter_id = int(query.data.split(":", 1)[1])
    chapter = db.get_chapter(chapter_id)
    if not chapter:
        await query.answer("Глава не найдена", show_alert=True)
        return
    paragraphs = db.list_paragraphs(chapter_id)
    text = (
        f"📖 <b>Глава {chapter.number}.</b> {chapter.title}\n"
        f"<i>{chapter.range_text}</i>\n\n"
        "Выберите параграф:"
    )
    await _safe_edit(query, text, keyboards.paragraphs_kb(chapter_id, paragraphs))


# ---- callback: paragraph -----------------------------------------------------


@router.callback_query(F.data.startswith("par:"))
async def cb_paragraph(query: CallbackQuery, db: Database) -> None:
    assert query.data is not None
    _, paragraph_id_s, page_s = query.data.split(":")
    paragraph_id = int(paragraph_id_s)
    page = int(page_s)
    paragraph = db.get_paragraph(paragraph_id)
    if not paragraph:
        await query.answer("Параграф не найден", show_alert=True)
        return
    chapter = db.get_chapter(paragraph.chapter_id)
    problems = db.list_problems(paragraph_id)
    with_solution = sum(1 for p in problems if p.has_solution)
    text = (
        f"📖 Глава {chapter.number if chapter else '?'} · §{paragraph.number}. "
        f"<b>{paragraph.title}</b>\n"
        f"<i>{paragraph.range_text}</i>\n\n"
        f"Всего задач: <b>{len(problems)}</b>, "
        f"с решением: <b>{with_solution}</b>.\n\n"
        "Точкой (·) отмечены задачи без решения. Нажмите номер, чтобы открыть."
    )
    markup = keyboards.problems_kb(paragraph_id, problems, page, paragraph.chapter_id)
    await _safe_edit(query, text, markup)


# ---- callback: problem card --------------------------------------------------


@router.callback_query(F.data.startswith("p:"))
async def cb_problem(query: CallbackQuery, db: Database) -> None:
    assert query.data is not None
    berman_number = int(query.data.split(":", 1)[1])
    if query.message is None:
        await query.answer()
        return
    if query.from_user:
        db.touch_user(query.from_user.id, query.from_user.username)
    await _send_problem(query.message, db, berman_number, replace=True)
    await query.answer()


# ---- /random -----------------------------------------------------------------


@router.message(Command("random"))
async def cmd_random(message: Message, db: Database) -> None:
    cur = db._conn.execute(
        "SELECT berman_number FROM problems WHERE has_solution = 1 ORDER BY RANDOM() LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        await message.answer("В базе пока нет ни одного решения.")
        return
    if message.from_user:
        db.touch_user(message.from_user.id, message.from_user.username)
    await _send_problem(message, db, int(row[0]), replace=False)


@router.callback_query(F.data == "random")
async def cb_random(query: CallbackQuery, db: Database) -> None:
    cur = db._conn.execute(
        "SELECT berman_number FROM problems WHERE has_solution = 1 ORDER BY RANDOM() LIMIT 1"
    )
    row = cur.fetchone()
    if not row or query.message is None:
        await query.answer("В базе пока нет ни одного решения.", show_alert=True)
        return
    if query.from_user:
        db.touch_user(query.from_user.id, query.from_user.username)
    await _send_problem(query.message, db, int(row[0]), replace=False)
    await query.answer()


# ---- helpers -----------------------------------------------------------------


async def _safe_edit(query: CallbackQuery, text: str, markup) -> None:
    if query.message is None:
        await query.answer()
        return
    try:
        await query.message.edit_text(
            text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup
        )
    except TelegramBadRequest:
        await query.message.answer(
            text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup
        )
    await query.answer()


def _neighbors(db: Database, problem: Problem) -> tuple[int | None, int | None]:
    cur = db._conn.execute(
        """
        SELECT berman_number FROM problems
        WHERE paragraph_id = ? AND berman_number < ?
        ORDER BY berman_number DESC LIMIT 1
        """,
        (problem.paragraph_id, problem.berman_number),
    )
    prev_row = cur.fetchone()
    cur = db._conn.execute(
        """
        SELECT berman_number FROM problems
        WHERE paragraph_id = ? AND berman_number > ?
        ORDER BY berman_number ASC LIMIT 1
        """,
        (problem.paragraph_id, problem.berman_number),
    )
    next_row = cur.fetchone()
    return (
        int(prev_row[0]) if prev_row else None,
        int(next_row[0]) if next_row else None,
    )


async def _send_problem(
    message: Message,
    db: Database,
    berman_number: int,
    replace: bool,
) -> None:
    """Send a problem card. If `replace` is true, attempts to edit the calling
    message; otherwise sends a new one. Always falls back to sending if editing
    fails (e.g. when the previous message is text-only and we want to send a
    photo)."""
    problem = db.get_problem_by_berman_number(berman_number)
    if problem is None:
        await message.answer(
            f"Задача №{berman_number} не найдена в базе.\n"
            "Возможно, такого номера нет в сборнике, либо база ещё не загружена."
        )
        return

    paragraph = db.get_paragraph(problem.paragraph_id)
    chapter = db.get_chapter(paragraph.chapter_id) if paragraph else None
    prev_b, next_b = _neighbors(db, problem)

    breadcrumb = ""
    if chapter and paragraph:
        breadcrumb = (
            f"Глава {chapter.number} · §{paragraph.number}. {paragraph.title}\n"
        )

    markup = keyboards.problem_card_kb(
        problem,
        paragraph.id if paragraph else 0,
        chapter.id if chapter else 0,
        prev_b,
        next_b,
    )

    if not problem.has_solution:
        text = (
            f"<b>Задача №{problem.berman_number}</b>\n"
            f"{breadcrumb}\n"
            "Решение этой задачи пока не добавлено в базу. "
            "Если вы знаете решение — напишите автору бота, мы добавим его."
        )
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)
        return

    caption = f"<b>Задача №{problem.berman_number}</b>"
    if breadcrumb:
        caption += f"\n<i>{breadcrumb.strip()}</i>"

    sent = None
    if problem.telegram_file_id:
        try:
            sent = await message.answer_photo(
                photo=problem.telegram_file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except TelegramBadRequest as e:
            log.warning("Cached file_id rejected for №%d: %s", berman_number, e)

    if sent is None and problem.image_path and Path(problem.image_path).exists():
        sent = await message.answer_photo(
            photo=FSInputFile(problem.image_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=markup,
        )
    elif sent is None:
        # No image yet: fall back to a plain link to source.
        text = (
            f"<b>Задача №{problem.berman_number}</b>\n"
            f"{breadcrumb}\n"
            "Картинка с решением ещё не отрендерена.\n"
        )
        if problem.source_url:
            text += f'Откройте на сайте: <a href="{problem.source_url}">{problem.source_url}</a>'
        await message.answer(
            text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup
        )
        return

    if sent and sent.photo:
        # Cache file_id so subsequent sends avoid re-uploading the file.
        db.update_telegram_file_id(problem.id, sent.photo[-1].file_id)
