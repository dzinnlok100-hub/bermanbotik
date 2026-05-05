"""Search handler — typing a number in chat opens that problem."""

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.types import Message

from ..db import Database
from .navigation import _send_problem

router = Router(name="search")


NUMBER_RE = re.compile(r"^\s*№?\s*(\d{1,5})\s*$")


@router.message(F.text)
async def search_by_number(message: Message, db: Database) -> None:
    if not message.text:
        return
    m = NUMBER_RE.match(message.text)
    if not m:
        return
    berman_number = int(m.group(1))
    if berman_number < 1 or berman_number > 5000:
        await message.answer(
            "Похоже на номер задачи, но в сборнике Бермана задач только до №4400."
        )
        return
    if message.from_user:
        db.touch_user(message.from_user.id, message.from_user.username)
    await _send_problem(message, db, berman_number, replace=False)
