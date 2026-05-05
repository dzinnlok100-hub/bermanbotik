"""Tests for the HTML parsing helpers (no network access)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from berman_bot.parser import (
    ParagraphMeta,
    _expand_paragraph_problems,
    _section_inner_html,
)


def test_section_inner_html_strips_heading() -> None:
    html = '<section><h2>Решение</h2><p>body <span>x</span></p></section>'
    soup = BeautifulSoup(html, "lxml")
    section = soup.find("section")
    inner = _section_inner_html(section)
    assert inner is not None
    assert inner.startswith("<p>")
    assert "Решение" not in inner


def test_section_inner_html_none() -> None:
    assert _section_inner_html(None) is None


def test_expand_paragraph_problems_fills_gaps() -> None:
    paragraph = ParagraphMeta(
        chapter_number=1,
        number=1,
        title="§1",
        range_text="№1 - №5",
        url="",
    )
    from berman_bot.parser import ProblemMeta

    scraped = [
        ProblemMeta(chapter_number=1, paragraph_number=1, berman_number=1, amk_internal_id=1000, url=""),
        ProblemMeta(chapter_number=1, paragraph_number=1, berman_number=4, amk_internal_id=1003, url=""),
    ]
    expanded = _expand_paragraph_problems(paragraph, scraped)
    assert expanded == [
        (1, 1000),
        (2, None),
        (3, None),
        (4, 1003),
        (5, None),
    ]


def test_expand_paragraph_problems_handles_no_range() -> None:
    paragraph = ParagraphMeta(chapter_number=1, number=1, title="§1", range_text="", url="")
    from berman_bot.parser import ProblemMeta

    scraped = [
        ProblemMeta(chapter_number=1, paragraph_number=1, berman_number=7, amk_internal_id=2000, url=""),
    ]
    expanded = _expand_paragraph_problems(paragraph, scraped)
    assert expanded == [(7, 2000)]
