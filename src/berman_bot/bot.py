"""Aiogram bot entrypoint."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, TelegramObject

from .config import get_settings
from .db import Database
from .handlers import build_router


class DatabaseMiddleware(BaseMiddleware):
    """Inject the shared `Database` instance into every handler call."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        return await handler(event, data)


async def _setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="menu", description="Оглавление сборника"),
            BotCommand(command="random", description="Случайная задача с решением"),
            BotCommand(command="stats", description="Статистика базы"),
            BotCommand(command="help", description="Помощь"),
        ]
    )


async def _run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings = get_settings()

    db = Database(settings.db_path)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(build_router())
    dp.update.outer_middleware(DatabaseMiddleware(db))

    await _setup_commands(bot)
    logging.info("Bot starting (long polling)")
    try:
        await dp.start_polling(bot)
    finally:
        db.close()
        await bot.session.close()


def main() -> None:
    """CLI entrypoint installed as `berman-bot`."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
