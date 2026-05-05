"""Tests for renderer template generation (no Playwright/network)."""

from __future__ import annotations

from berman_bot.db import Problem
from berman_bot.renderer import build_html


def _problem(**overrides) -> Problem:
    base = {
        "id": 1,
        "berman_number": 1,
        "paragraph_id": 1,
        "amk_internal_id": 1000,
        "source_url": "https://amkbook.net/problem/1000",
        "statement_html": "<p>statement</p>",
        "solution_html": "<p>solution</p>",
        "answer_html": "<p>answer</p>",
        "image_path": None,
        "telegram_file_id": None,
        "has_solution": True,
        "user_added": False,
    }
    base.update(overrides)
    return Problem(**base)


def test_build_html_includes_all_sections() -> None:
    html = build_html(_problem())
    assert "Задача №1" in html
    assert "<h2>Условие</h2>" in html
    assert "<h2>Решение</h2>" in html
    assert "<h2>Ответ</h2>" in html
    assert "https://amkbook.net/problem/1000" in html


def test_build_html_skips_empty_sections() -> None:
    html = build_html(_problem(answer_html=None, solution_html=""))
    assert "<h2>Условие</h2>" in html
    assert "<h2>Решение</h2>" not in html
    assert "<h2>Ответ</h2>" not in html


def test_build_html_handles_missing_source() -> None:
    html = build_html(_problem(source_url=None))
    assert "Источник:" not in html
