"""Smoke tests for the SQLite storage layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from berman_bot.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def test_chapters_paragraphs_problems_roundtrip(db: Database) -> None:
    chapter_id = db.upsert_chapter(1, "Функции", "№1 - №166")
    paragraph_id = db.upsert_paragraph(chapter_id, 1, "Сведения о функции", "№1 - №39")

    pid = db.upsert_problem(
        berman_number=1,
        paragraph_id=paragraph_id,
        amk_internal_id=1000,
        source_url="https://amkbook.net/problem/1000",
        statement_html="<p>statement</p>",
        solution_html="<p>solution</p>",
        answer_html="<p>answer</p>",
    )
    assert pid > 0

    chapters = db.list_chapters()
    assert len(chapters) == 1
    assert chapters[0].number == 1

    paragraphs = db.list_paragraphs(chapter_id)
    assert len(paragraphs) == 1

    problems = db.list_problems(paragraph_id)
    assert len(problems) == 1
    assert problems[0].berman_number == 1
    assert problems[0].has_solution is True

    fetched = db.get_problem_by_berman_number(1)
    assert fetched is not None
    assert fetched.solution_html == "<p>solution</p>"


def test_upsert_problem_preserves_existing_html(db: Database) -> None:
    chapter_id = db.upsert_chapter(1, "Функции", "")
    paragraph_id = db.upsert_paragraph(chapter_id, 1, "§1", "")

    db.upsert_problem(berman_number=10, paragraph_id=paragraph_id, amk_internal_id=2000)
    db.update_problem_html(10, "<p>S</p>", "<p>sol</p>", "<p>ans</p>")

    fetched = db.get_problem_by_berman_number(10)
    assert fetched is not None
    assert fetched.has_solution is True
    assert fetched.solution_html == "<p>sol</p>"

    # Re-upsert without HTML must not erase the existing solution.
    db.upsert_problem(
        berman_number=10,
        paragraph_id=paragraph_id,
        amk_internal_id=2000,
        source_url="https://example.com/2000",
    )

    fetched = db.get_problem_by_berman_number(10)
    assert fetched is not None
    assert fetched.solution_html == "<p>sol</p>"
    assert fetched.source_url == "https://example.com/2000"


def test_problems_needing_detail(db: Database) -> None:
    chapter_id = db.upsert_chapter(1, "Функции", "")
    paragraph_id = db.upsert_paragraph(chapter_id, 1, "§1", "")

    db.upsert_problem(berman_number=1, paragraph_id=paragraph_id, amk_internal_id=1000)
    db.upsert_problem(berman_number=2, paragraph_id=paragraph_id)  # no amk_id
    db.upsert_problem(berman_number=3, paragraph_id=paragraph_id, amk_internal_id=1003)
    db.update_problem_html(3, "<p>S</p>", "<p>sol</p>", "<p>ans</p>")

    pending = db.problems_needing_detail()
    assert pending == [(1, 1000)]


def test_stats(db: Database) -> None:
    chapter_id = db.upsert_chapter(1, "Функции", "")
    paragraph_id = db.upsert_paragraph(chapter_id, 1, "§1", "")
    db.upsert_problem(berman_number=1, paragraph_id=paragraph_id, amk_internal_id=1000)
    db.update_problem_html(1, "<p>S</p>", "<p>sol</p>", "<p>ans</p>")
    db.upsert_problem(berman_number=2, paragraph_id=paragraph_id)

    s = db.stats()
    assert s["chapters"] == 1
    assert s["paragraphs"] == 1
    assert s["problems_total"] == 2
    assert s["problems_with_solution"] == 1
    assert s["problems_with_image"] == 0
