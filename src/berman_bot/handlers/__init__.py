"""Aiogram routers."""

from aiogram import Router

from . import admin, navigation, search, start


def build_router() -> Router:
    """Combine all routers in the correct precedence order."""
    main = Router(name="main")
    main.include_router(start.router)
    main.include_router(admin.router)
    main.include_router(navigation.router)
    main.include_router(search.router)
    return main


__all__ = ["build_router"]
