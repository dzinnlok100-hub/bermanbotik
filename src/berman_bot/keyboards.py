"""Inline keyboard factories."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .db import Chapter, Paragraph, Problem

PROBLEMS_PER_PAGE = 24
PROBLEMS_PER_ROW = 4


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📚 Оглавление", callback_data="menu:chapters")
    kb.button(text="🎲 Случайная", callback_data="random")
    kb.button(text="❓ Помощь", callback_data="help")
    kb.adjust(2, 1)
    return kb.as_markup()


def chapters_kb(chapters: list[Chapter]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ch in chapters:
        kb.button(
            text=f"Глава {ch.number}. {ch.title}",
            callback_data=f"ch:{ch.id}",
        )
    kb.adjust(1)
    return kb.as_markup()


def paragraphs_kb(chapter_id: int, paragraphs: list[Paragraph]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in paragraphs:
        label = f"§{p.number}. {p.title}"
        if len(label) > 60:
            label = label[:57] + "…"
        kb.button(text=label, callback_data=f"par:{p.id}:0")
    kb.button(text="« Главы", callback_data="menu:chapters")
    kb.adjust(1)
    return kb.as_markup()


def problems_kb(
    paragraph_id: int, problems: list[Problem], page: int, chapter_id: int
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    total_pages = max(1, (len(problems) + PROBLEMS_PER_PAGE - 1) // PROBLEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PROBLEMS_PER_PAGE
    end = start + PROBLEMS_PER_PAGE
    page_problems = problems[start:end]

    for problem in page_problems:
        marker = "" if problem.has_solution else "·"
        kb.button(
            text=f"{problem.berman_number}{marker}",
            callback_data=f"p:{problem.berman_number}",
        )

    kb.adjust(*([PROBLEMS_PER_ROW] * (len(page_problems) // PROBLEMS_PER_ROW + 1)))

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="← Назад", callback_data=f"par:{paragraph_id}:{page - 1}")
        )
    nav.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
    )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(text="Вперёд →", callback_data=f"par:{paragraph_id}:{page + 1}")
        )
    if nav:
        kb.row(*nav)

    kb.row(
        InlineKeyboardButton(text="« Параграфы", callback_data=f"ch:{chapter_id}"),
        InlineKeyboardButton(text="« Главы", callback_data="menu:chapters"),
    )

    return kb.as_markup()


def problem_card_kb(
    problem: Problem,
    paragraph_id: int,
    chapter_id: int,
    prev_berman: int | None,
    next_berman: int | None,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    nav: list[InlineKeyboardButton] = []
    if prev_berman is not None:
        nav.append(InlineKeyboardButton(text=f"← №{prev_berman}", callback_data=f"p:{prev_berman}"))
    if next_berman is not None:
        nav.append(InlineKeyboardButton(text=f"№{next_berman} →", callback_data=f"p:{next_berman}"))
    if nav:
        kb.row(*nav)

    if problem.source_url:
        kb.row(InlineKeyboardButton(text="🌐 Источник", url=problem.source_url))

    kb.row(
        InlineKeyboardButton(text="К списку задач", callback_data=f"par:{paragraph_id}:0"),
        InlineKeyboardButton(text="« Главы", callback_data="menu:chapters"),
    )
    return kb.as_markup()
